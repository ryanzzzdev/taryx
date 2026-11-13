"""Billing admission, outbox processing and atomic issuance.

Admission is durable before any task dispatch: the operation and its
outbox event commit together, so broker downtime never loses intent and
at-least-once processing is safe. Issuance is one transaction: staleness
precondition, numbered invoice, balanced journal and operation/outbox
completion — or nothing at all.
"""

import hashlib
import logging
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
from taryx.core.pricing.services import lock_inputs

# Minimal fictional-retailer chart of accounts (billing subledger).
ACC_RECEIVABLE = "1100"
ACC_GST_LIABILITY = "2100"
ACC_ENERGY_REVENUE = "4000"
ACC_EXPORT_CREDIT = "4100"

TOPIC_ISSUE = "billing.issue"

logger = logging.getLogger("taryx.billing")


class AdmissionError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


class CalculationUnavailable(Exception):
    """The pinned authoritative engine could not produce a result.

    Transient by definition: the operation stays PENDING (in-flight) so
    it also blocks cohort mode changes until it resolves or is replaced.
    """

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


def _payload_sha(
    account: Account,
    period_start,
    period_end,
    rating_run: RatingRun,
    cohort_mode: str,
    cohort_revision: int,
) -> str:
    return hashlib.sha256(
        f"{account.reference}|{period_start}|{period_end}|{rating_run.id}"
        f"|{cohort_mode}|{cohort_revision}".encode()
    ).hexdigest()


def admit_issue(
    account: Account,
    period_start,
    period_end,
    rating_run: RatingRun,
    operation_id: str,
    *,
    routing_resolver=None,
) -> BillingOperation:
    """Durably admit a billing operation and its outbox event atomically.

    Processing routes on billed state: the first operation for a period
    issues the invoice; a later operation pinned to a different input
    digest posts a linked adjustment instead. The caller may enqueue a
    fast-path task afterwards; if the broker is down the pending outbox
    event is recovered by drain_outbox.

    The routing pin is resolved under the account row lock: the lock
    conflicts with a cohort cutover's member locks, so an admission can
    never pin a routing identity after the cutover's final pending-ops
    check but before the route commit.
    """
    try:
        with transaction.atomic():
            Account.objects.select_for_update().get(pk=account.pk)
            if routing_resolver is None:
                cohort_mode, cohort_revision = "new_only", 0
            else:
                cohort_mode, cohort_revision = routing_resolver(account)
            payload = _payload_sha(
                account,
                period_start,
                period_end,
                rating_run,
                cohort_mode,
                cohort_revision,
            )
            op = BillingOperation.objects.create(
                operation_id=operation_id,
                account=account,
                period_start=period_start,
                period_end=period_end,
                rating_run=rating_run,
                payload_sha256=payload,
                cohort_mode=cohort_mode,
                cohort_revision=cohort_revision,
            )
            OutboxEvent.objects.create(operation=op, topic=TOPIC_ISSUE)
        return op
    except IntegrityError:
        # Loser of a concurrent same-key admission: resolve the winner.
        existing = BillingOperation.objects.get(operation_id=operation_id)
        if existing.payload_sha256 != payload:
            raise AdmissionError(
                "operation_conflict",
                f"operation {operation_id!r} already admitted with a different payload",
            ) from None
        return existing


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
        "net": run.net,
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


def _signed_leg(journal: JournalEntry, code: str, delta: Decimal, memo: str) -> Posting | None:
    """One leg per element; a negative amount swaps the side so net-credit
    bills (export exceeding charges) post to the correct ledger side."""
    return _leg(journal, code, max(delta, 0), max(-delta, 0), memo)


def _authoritative_amounts(op: BillingOperation, legacy_calculator) -> dict[str, Decimal]:
    """Amounts per the op's pinned routing mode: under legacy_only/shadow
    the legacy calculator is authoritative; otherwise the rating run."""
    if op.cohort_mode in {"legacy_only", "shadow"}:
        if legacy_calculator is None:
            raise CalculationUnavailable(
                "no_calculator", "no legacy calculator configured for legacy routing"
            )
        return legacy_calculator(op)
    return _run_amounts(op.rating_run)


def _issue(op: BillingOperation, amounts: dict[str, Decimal]) -> Invoice:
    run = op.rating_run
    invoice = Invoice.objects.create(
        number=_next_number("billing_invoice_number_seq", "INV"),
        account=op.account,
        period_start=op.period_start,
        period_end=op.period_end,
        rating_run=run,
        input_digest=run.input_digest,
        calculation_source=_op_source(op),
        legacy_calculation_id=getattr(op, "_legacy_calculation_id", None),
        net=amounts["net"],
        gst=amounts["gst"],
        total=amounts["total"],
    )
    journal = JournalEntry.objects.create(
        invoice=invoice,
        operation=op,
        memo=f"{invoice.number} {op.account.reference} {op.period_start}..{op.period_end}",
    )
    postings = [
        _signed_leg(journal, ACC_RECEIVABLE, amounts["total"], f"receivable {invoice.number}"),
        _signed_leg(
            journal, ACC_ENERGY_REVENUE, -amounts["charge"], f"energy+supply {invoice.number}"
        ),
        _signed_leg(
            journal, ACC_EXPORT_CREDIT, amounts["export"], f"feed-in credit {invoice.number}"
        ),
        _signed_leg(journal, ACC_GST_LIABILITY, -amounts["gst"], f"gst {invoice.number}"),
    ]
    Posting.objects.bulk_create(p for p in postings if p is not None)
    return invoice


def _op_source(op: BillingOperation) -> str:
    return "legacy" if op.cohort_mode in {"legacy_only", "shadow"} else "new"


def _post_correction(
    op: BillingOperation, invoice: Invoice, generation: int, revised: dict[str, Decimal]
) -> Adjustment:
    """Append a linked adjustment reconciling the revised calculation
    against the liability already recognised on this invoice (invoice
    row lock held)."""
    run = op.rating_run
    recognised = _recognised_amounts(invoice)
    delta = {key: revised[key] - recognised[key] for key in recognised}
    adjustment = Adjustment.objects.create(
        number=_next_number("billing_adjustment_number_seq", "ADJ"),
        invoice=invoice,
        rating_run=run,
        input_digest=run.input_digest,
        calculation_source=_op_source(op),
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

        postings = [
            _signed_leg(journal, ACC_RECEIVABLE, delta["total"], "receivable"),
            _signed_leg(journal, ACC_ENERGY_REVENUE, -delta["charge"], "energy+supply"),
            _signed_leg(journal, ACC_EXPORT_CREDIT, delta["export"], "feed-in credit"),
            _signed_leg(journal, ACC_GST_LIABILITY, -delta["gst"], "gst"),
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
    logger.info(
        "billing operation finished",
        extra={
            "operation_id": str(op.operation_id),
            "outcome": status,
            "account": op.account.reference,
        },
    )
    return op


def process_operation(
    operation_id: str,
    *,
    digest_resolver: Callable[[Account, object, object], str],
    routing_resolver: Callable[[Account], tuple[str, int]] | None = None,
    legacy_calculator: Callable[[BillingOperation], dict] | None = None,
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

        if digest_resolver(op.account, op.period_start, op.period_end) != (
            op.rating_run.input_digest
        ):
            return _finish(
                op,
                BillingOperation.Status.STALE,
                "input selection changed since the pinned rating run",
            )

        # Routing pin re-check: the cohort mode/revision this op was
        # admitted under must still be current. (Mode changes are already
        # blocked while ops are pending; this guard also catches a cohort
        # membership adopted after admission.)
        if routing_resolver is not None:
            current_mode, current_revision = routing_resolver(op.account)
            if (current_mode, current_revision) != (
                op.cohort_mode,
                op.cohort_revision,
            ):
                return _finish(
                    op,
                    BillingOperation.Status.STALE,
                    "cohort routing changed since admission",
                )

        # Under legacy routing the authoritative amounts come from a
        # remote call that also writes shadow-alias evidence. It must run
        # BEFORE lock_inputs: the shadow connection's FK checks wait on
        # FOR UPDATE locks held by this transaction (account lock →
        # deadlock the database cannot detect cross-connection).
        try:
            amounts = _authoritative_amounts(op, legacy_calculator)
        except CalculationUnavailable as exc:
            if exc.code != "malformed":
                raise
            # A malformed authoritative response is deterministic —
            # retrying the identical request reproduces it, so the op
            # fails terminally rather than retrying forever.
            return _finish(
                op,
                BillingOperation.Status.FAILED,
                f"authoritative response rejected: {exc}",
            )

        # Commit-safe revalidation: lock the account and every row feeding
        # the digest, then recompute under those locks. Any input change
        # committed meanwhile is now visible (stale); a change still in
        # flight either already holds these locks (we wait, then see it) or
        # blocks on the account lock it must take before mutating, so it
        # can only land after this transaction commits. The digest also
        # covers open quarantines, which input locks alone cannot pin.
        lock_inputs(op.account, op.period_start, op.period_end)
        # Routing pin re-check under the input locks: a cutover committed
        # while this transaction waited on the account lock must not
        # issue under the admitted legacy pin.
        if routing_resolver is not None:
            current_mode, current_revision = routing_resolver(op.account)
            if (current_mode, current_revision) != (
                op.cohort_mode,
                op.cohort_revision,
            ):
                return _finish(
                    op,
                    BillingOperation.Status.STALE,
                    "cohort routing changed during issuance validation",
                )
        if digest_resolver(op.account, op.period_start, op.period_end) != (
            op.rating_run.input_digest
        ):
            return _finish(
                op,
                BillingOperation.Status.STALE,
                "inputs changed during issuance validation",
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
                    invoice = _issue(op, amounts)
            except IntegrityError as exc:
                # Only the generation-key uniqueness violation means a
                # racing issuance already posted; anything else is a real
                # failure and must surface rather than hang the operation.
                if "uniq_bill_generation" not in str(exc):
                    raise
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
            op_source = _op_source(op)
            same_source = recognised.calculation_source == op_source
            if recognised.input_digest == run.input_digest and same_source:
                # Repeat of the currently recognised generation — same
                # inputs under the same authoritative engine.
                op.invoice = invoice
                op.adjustment = latest
            elif run.id <= recognised.rating_run_id and same_source:
                return _finish(
                    op,
                    BillingOperation.Status.STALE,
                    "calculation superseded by a newer recognised generation",
                )
            else:
                op.invoice = invoice
                op.adjustment = _post_correction(
                    op,
                    invoice,
                    generation=(latest.generation if latest else 0) + 1,
                    revised=amounts,
                )

        _finish(op, BillingOperation.Status.COMPLETE)
        if os.environ.get("TARYX_BILLING_CRASH") == "before_commit":
            os._exit(1)  # test-only crash point: die before the txn commits
    return op


def drain_outbox(
    *,
    digest_resolver: Callable[[Account, object, object], str],
    routing_resolver: Callable[[Account], tuple[str, int]] | None = None,
    legacy_calculator: Callable[[BillingOperation], dict] | None = None,
    limit: int = 200,
) -> list[BillingOperation]:
    """Recover pending outbox events (broker outage, lost tasks).

    Each event is processed independently: a failure is recorded on its
    outbox row (attempts/last_error) and skipped, so one unavailable
    calculation cannot starve later recoverable work in the same batch.
    Selection orders by attempts so chronic failures sink below fresh
    work and a batch of them can never starve a new event — but events
    are never excluded, so recovered dependencies complete on the next
    drain. All selected events are attempted before the first failure
    is re-raised.
    """
    pending = list(
        OutboxEvent.objects.filter(delivered_at__isnull=True)
        .order_by("attempts", "created_at")
        .select_related("operation")[:limit]
    )
    processed, failures = [], []
    for event in pending:
        try:
            processed.append(
                process_operation(
                    event.operation.operation_id,
                    digest_resolver=digest_resolver,
                    routing_resolver=routing_resolver,
                    legacy_calculator=legacy_calculator,
                )
            )
        except Exception as exc:
            event.attempts += 1
            event.last_error = f"{type(exc).__name__}: {exc}"[:400]
            event.save(update_fields=["attempts", "last_error"])
            logger.warning(
                "outbox delivery failed",
                extra={
                    "operation_id": str(event.operation.operation_id),
                    "attempt": event.attempts,
                    "error": type(exc).__name__,
                },
            )
            failures.append(exc)
    if failures:
        raise failures[0]
    return processed
