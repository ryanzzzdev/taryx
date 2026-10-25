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
from decimal import Decimal

from django.db import connection, transaction
from django.db.models import Sum
from django.db.utils import IntegrityError
from django.utils import timezone

from taryx.core.accounts.models import Account
from taryx.core.billing.models import (
    Adjustment,
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

    Processing routes on billed state: the first operation for a period
    issues the invoice; a later operation pinned to a different input
    digest posts a linked adjustment instead. The caller may enqueue a
    fast-path task afterwards; if the broker is down the pending outbox
    event is recovered by drain_outbox.
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


def _next_number(sequence: str, prefix: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT nextval('{sequence}')")
        (value,) = cursor.fetchone()
    return f"{prefix}-{value:06d}"


def _run_amounts(run: RatingRun) -> dict[str, Decimal]:
    """Element-level monetary result of a rating run."""
    zero = type(run.net)(0)
    return {
        "charge": sum(
            (line.amount for line in run.lines.all() if line.element in {"import", "supply"}),
            start=zero,
        ),
        "export": -sum(
            (line.amount for line in run.lines.all() if line.element == "export_credit"),
            start=zero,
        ),
        "gst": run.gst,
        "total": run.total,
    }


def _recognised_amounts(invoice: Invoice) -> dict[str, Decimal]:
    """Liability already recognised by every journal posted to an invoice.

    The ledger is the source of truth: revenue/GST legs are credit-positive,
    receivable/export legs debit-positive."""
    legs = (
        Posting.objects.filter(journal__invoice=invoice)
        .values("account_code")
        .annotate(dr=Sum("debit"), cr=Sum("credit"))
    )
    zero = Decimal(0)
    balance = {row["account_code"]: (row["dr"] or zero) - (row["cr"] or zero) for row in legs}
    return {
        "charge": -balance.get(ACC_ENERGY_REVENUE, zero),
        "export": balance.get(ACC_EXPORT_CREDIT, zero),
        "gst": -balance.get(ACC_GST_LIABILITY, zero),
        "total": balance.get(ACC_RECEIVABLE, zero),
    }


def _leg(journal: JournalEntry, code: str, debit, credit, memo: str) -> Posting | None:
    if not debit and not credit:
        return None
    return Posting(journal=journal, account_code=code, debit=debit, credit=credit, memo=memo)


def _issue(op: BillingOperation) -> Invoice:
    run = op.rating_run
    amounts = _run_amounts(run)
    invoice = Invoice.objects.create(
        number=_next_number("billing_invoice_number_seq", "INV"),
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
        operation=op,
        memo=f"{invoice.number} {op.account.reference} {op.period_start}..{op.period_end}",
    )
    postings = [
        _leg(journal, ACC_RECEIVABLE, invoice.total, 0, f"receivable {invoice.number}"),
        _leg(journal, ACC_ENERGY_REVENUE, 0, amounts["charge"], f"energy+supply {invoice.number}"),
        _leg(journal, ACC_EXPORT_CREDIT, amounts["export"], 0, f"feed-in credit {invoice.number}"),
        _leg(journal, ACC_GST_LIABILITY, 0, invoice.gst, f"gst {invoice.number}"),
    ]
    Posting.objects.bulk_create(p for p in postings if p is not None)
    return invoice


def _post_correction(op: BillingOperation, invoice: Invoice, generation: int) -> Adjustment:
    """Append a linked adjustment reconciling the revised run against the
    liability already recognised on this invoice (invoice row lock held)."""
    run = op.rating_run
    revised = _run_amounts(run)
    recognised = _recognised_amounts(invoice)
    delta = {key: revised[key] - recognised[key] for key in revised}
    adjustment = Adjustment.objects.create(
        number=_next_number("billing_adjustment_number_seq", "ADJ"),
        invoice=invoice,
        rating_run=run,
        input_digest=run.input_digest,
        generation=generation,
        delta_charge=delta["charge"],
        delta_export=delta["export"],
        delta_gst=delta["gst"],
        delta_total=delta["total"],
    )
    if any(delta.values()):
        journal = JournalEntry.objects.create(
            invoice=invoice,
            adjustment=adjustment,
            operation=op,
            memo=f"{adjustment.number} correction for {invoice.number}",
        )

        def signed(code: str, delta_dr, memo: str):
            """One leg per element; a negative delta swaps the side."""
            return _leg(journal, code, max(delta_dr, 0), max(-delta_dr, 0), memo)

        postings = [
            signed(ACC_RECEIVABLE, delta["total"], "receivable"),
            signed(ACC_ENERGY_REVENUE, -delta["charge"], "energy+supply"),
            signed(ACC_EXPORT_CREDIT, delta["export"], "feed-in credit"),
            signed(ACC_GST_LIABILITY, -delta["gst"], "gst"),
        ]
        Posting.objects.bulk_create(p for p in postings if p is not None)
    return adjustment


def _finish(op: BillingOperation, status: str, detail: str = "") -> BillingOperation:
    op.status = status
    op.detail = detail
    op.completed_at = timezone.now()
    op.save(update_fields=["status", "detail", "completed_at", "invoice", "adjustment"])
    op.outbox_event.delivered_at = op.completed_at
    op.outbox_event.save(update_fields=["delivered_at"])
    return op


def process_operation(
    operation_id: str, *, digest_resolver: Callable[[Account, object, object], str]
) -> BillingOperation:
    """Process one admitted operation idempotently under its row lock.

    Routes on the billed state of the account/period: no invoice issues
    one; an invoice with a different pinned digest posts a linked
    adjustment against the recognised generation. The invoice row lock
    serializes adjustment generations so concurrent revisions and stale
    calculations cannot supersede the newest recognised run."""
    with transaction.atomic():
        op = BillingOperation.objects.select_for_update().get(operation_id=operation_id)
        if op.status != BillingOperation.Status.PENDING:
            return op  # duplicate delivery is a no-op

        current_digest = digest_resolver(op.account, op.period_start, op.period_end)
        if current_digest != op.rating_run.input_digest:
            return _finish(
                op,
                BillingOperation.Status.STALE,
                "input selection changed since the pinned rating run",
            )

        invoice = (
            Invoice.objects.select_for_update()
            .filter(
                account=op.account,
                period_start=op.period_start,
                period_end=op.period_end,
            )
            .order_by("id")
            .first()
        )
        if invoice is None:
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
            op.invoice = invoice
        else:
            run = op.rating_run
            latest = invoice.adjustments.order_by("-generation").first()
            recognised = latest or invoice
            if recognised.input_digest == run.input_digest:
                # Repeat of the currently recognised generation.
                op.invoice = invoice
                op.adjustment = latest
            elif run.id <= recognised.rating_run_id:
                return _finish(
                    op,
                    BillingOperation.Status.STALE,
                    "calculation superseded by a newer recognised generation",
                )
            else:
                op.invoice = invoice
                op.adjustment = _post_correction(
                    op, invoice, generation=(latest.generation if latest else 0) + 1
                )

        _finish(op, BillingOperation.Status.COMPLETE)
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
