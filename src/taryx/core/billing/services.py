"""Billing admission, outbox processing and atomic issuance.

Admission is durable before any task dispatch: the operation and its
outbox event commit together, so broker downtime never loses intent and
at-least-once processing is safe. Issuance is one transaction: staleness
precondition, numbered invoice, balanced journal and operation/outbox
completion — or nothing at all.
"""

import hashlib
import os
from collections.abc import Callable

from django.db import connection, transaction
from django.db.utils import IntegrityError
from django.utils import timezone

from taryx.core.accounts.models import Account
from taryx.core.billing.models import (
    BillingOperation,
    Invoice,
    JournalEntry,
    OutboxEvent,
    Posting,
)
from taryx.core.pricing.models import RatingRun

# Minimal fictional-retailer chart of accounts (billing subledger).
ACC_RECEIVABLE = "1100"
ACC_GST_LIABILITY = "2100"
ACC_ENERGY_REVENUE = "4000"
ACC_EXPORT_CREDIT = "4100"

TOPIC_ISSUE = "billing.issue"


class AdmissionError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


def _payload_sha(account: Account, period_start, period_end, rating_run: RatingRun) -> str:
    return hashlib.sha256(
        f"{account.reference}|{period_start}|{period_end}|{rating_run.id}".encode()
    ).hexdigest()


def admit_issue(
    account: Account,
    period_start,
    period_end,
    rating_run: RatingRun,
    operation_id: str,
) -> BillingOperation:
    """Durably admit a billing operation and its outbox event atomically.

    The caller may enqueue a fast-path task afterwards; if the broker is
    down the pending outbox event is recovered by drain_outbox.
    """
    payload = _payload_sha(account, period_start, period_end, rating_run)
    existing = BillingOperation.objects.filter(operation_id=operation_id).first()
    if existing is not None:
        if existing.payload_sha256 != payload:
            raise AdmissionError(
                "operation_conflict",
                f"operation {operation_id!r} already admitted with a different payload",
            )
        return existing
    with transaction.atomic():
        op = BillingOperation.objects.create(
            operation_id=operation_id,
            account=account,
            period_start=period_start,
            period_end=period_end,
            rating_run=rating_run,
            payload_sha256=payload,
        )
        OutboxEvent.objects.create(operation=op, topic=TOPIC_ISSUE)
    return op


def _next_invoice_number() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval('billing_invoice_number_seq')")
        (value,) = cursor.fetchone()
    return f"INV-{value:06d}"


def _issue(op: BillingOperation) -> Invoice:
    run = op.rating_run
    invoice = Invoice.objects.create(
        number=_next_invoice_number(),
        account=op.account,
        period_start=op.period_start,
        period_end=op.period_end,
        rating_run=run,
        input_digest=run.input_digest,
        net=run.net,
        gst=run.gst,
        total=run.total,
    )
    journal = JournalEntry.objects.create(
        invoice=invoice,
        memo=f"{invoice.number} {op.account.reference} {op.period_start}..{op.period_end}",
    )
    charge = sum(
        (line.amount for line in run.lines.all() if line.element in {"import", "supply"}),
        start=type(run.net)(0),
    )
    export = -sum(
        (line.amount for line in run.lines.all() if line.element == "export_credit"),
        start=type(run.net)(0),
    )
    postings = [
        Posting(
            journal=journal,
            account_code=ACC_RECEIVABLE,
            debit=invoice.total,
            memo=f"receivable {invoice.number}",
        ),
        Posting(
            journal=journal,
            account_code=ACC_ENERGY_REVENUE,
            credit=charge,
            memo=f"energy+supply {invoice.number}",
        ),
    ]
    if export:
        postings.append(
            Posting(
                journal=journal,
                account_code=ACC_EXPORT_CREDIT,
                debit=export,
                memo=f"feed-in credit {invoice.number}",
            )
        )
    if invoice.gst:
        postings.append(
            Posting(
                journal=journal,
                account_code=ACC_GST_LIABILITY,
                credit=invoice.gst,
                memo=f"gst {invoice.number}",
            )
        )
    Posting.objects.bulk_create(postings)
    return invoice


def process_operation(
    operation_id: str, *, digest_resolver: Callable[[Account, object, object], str]
) -> BillingOperation:
    """Process one admitted operation idempotently under its row lock."""
    with transaction.atomic():
        op = BillingOperation.objects.select_for_update().get(operation_id=operation_id)
        if op.status != BillingOperation.Status.PENDING:
            return op  # duplicate delivery is a no-op

        current_digest = digest_resolver(op.account, op.period_start, op.period_end)
        if current_digest != op.rating_run.input_digest:
            op.status = BillingOperation.Status.STALE
            op.detail = "input selection changed since the pinned rating run"
            op.completed_at = timezone.now()
            op.save(update_fields=["status", "detail", "completed_at"])
            op.outbox_event.delivered_at = op.completed_at
            op.outbox_event.save(update_fields=["delivered_at"])
            return op

        try:
            with transaction.atomic():
                invoice = _issue(op)
        except IntegrityError:
            # A racing operation already issued this generation.
            invoice = Invoice.objects.get(
                account=op.account,
                period_start=op.period_start,
                period_end=op.period_end,
                input_digest=op.rating_run.input_digest,
            )
        op.status = BillingOperation.Status.COMPLETE
        op.invoice = invoice
        op.completed_at = timezone.now()
        op.save(update_fields=["status", "invoice", "completed_at"])
        op.outbox_event.delivered_at = op.completed_at
        op.outbox_event.save(update_fields=["delivered_at"])

        if os.environ.get("TARYX_BILLING_CRASH") == "before_commit":
            os._exit(1)  # test-only crash point: die before the txn commits
    return op


def drain_outbox(
    *, digest_resolver: Callable[[Account, object, object], str], limit: int = 200
) -> list[BillingOperation]:
    """Recover pending outbox events (broker outage, lost tasks)."""
    pending = list(
        OutboxEvent.objects.filter(delivered_at__isnull=True)
        .order_by("created_at")
        .values_list("operation__operation_id", flat=True)[:limit]
    )
    return [
        process_operation(operation_id, digest_resolver=digest_resolver) for operation_id in pending
    ]
