"""Bounded operator GraphQL contract (decision 004).

Session-authenticated; role groups viewer/operator/approver are enforced
server-side here. Mutations return payload objects with stable `code`
values instead of throwing GraphQL errors for domain failures, so the
portal renders outcomes deterministically and can poll operations.
"""

from contextlib import suppress
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import graphene
from django.contrib.auth import authenticate, login, logout
from graphene_django import DjangoObjectType
from graphql import GraphQLError

from taryx.composition.policy import policy as _policy
from taryx.composition.tasks import market_submit, process_billing_operation
from taryx.core.accounts.models import Account, MeterChannel, SupplyPoint
from taryx.core.audit.models import record as audit_record
from taryx.core.billing.models import (
    Adjustment,
    BillingOperation,
    Invoice,
    JournalEntry,
    Posting,
)
from taryx.core.billing.services import AdmissionError, admit_issue
from taryx.core.market.models import MarketException, TransferWorkflow
from taryx.core.market.services import request_transfer
from taryx.core.metering.ingestion import (
    ResolutionError,
    ingest_nem12_content,
    resolve_quarantine,
)
from taryx.core.metering.models import (
    CurrentInterval,
    IngestionBatch,
    IntervalRecord,
    QuarantinedInterval,
)
from taryx.core.metering.nem_time import nem_interval_end_utc
from taryx.core.migration.models import (
    SHADOW_ALIAS,
    Cohort,
    CohortEvent,
    ComparisonRun,
    LegacyCalculation,
)
from taryx.core.migration.services import (
    MigrationError,
    decide_discrepancy,
    evaluation_blockers,
    routing_for,
    run_comparison,
    transition_cohort,
)
from taryx.core.pricing.engine import RatingError
from taryx.core.pricing.models import RatingRun
from taryx.core.pricing.services import rate_account

MAX_LIMIT = 200


def _policy_kwargs() -> dict:
    resolved = _policy()
    return {
        "tariffs": resolved.TARIFFS,
        "gst_rate": resolved.GST_RATE,
        "policy_identity": resolved.POLICY_IDENTITY,
    }


class PermissionError_(GraphQLError):
    def __init__(self):
        super().__init__("permission_denied", extensions={"code": "permission_denied"})


def _user(info):
    user = info.context.user
    return user if user and user.is_authenticated else None


def _actor(info) -> str:
    user = _user(info)
    return user.username if user else "anonymous"


def _require_auth(info):
    if _user(info) is None:
        raise PermissionError_()


def _require_group(info, *groups: str) -> None:
    user = _user(info)
    if user is None or not user.groups.filter(name__in=groups).exists():
        raise PermissionError_()


def _role(user) -> str | None:
    for role in ("approver", "operator", "viewer"):
        if user.groups.filter(name=role).exists():
            return role
    return None


def _bounded(qs, limit: int | None):
    return qs[: min(limit or 50, MAX_LIMIT)]


class SupplyPointType(DjangoObjectType):
    class Meta:
        model = SupplyPoint
        fields = ("id", "nmi")


class MeterChannelType(DjangoObjectType):
    class Meta:
        model = MeterChannel
        fields = ("id", "suffix", "direction", "uom", "interval_minutes")


class AccountType(DjangoObjectType):
    supply_points = graphene.List(SupplyPointType, required=True)
    channels = graphene.List(MeterChannelType, required=True)

    class Meta:
        model = Account
        fields = ("id", "reference", "name")

    def resolve_supply_points(account, info):
        return account.supply_points.all()

    def resolve_channels(account, info):
        return MeterChannel.objects.filter(supply_point__account=account)


class IngestionBatchType(DjangoObjectType):
    class Meta:
        model = IngestionBatch
        fields = (
            "id",
            "source_name",
            "status",
            "record_count",
            "accepted_count",
            "quarantined_count",
            "error_code",
            "error_detail",
            "received_at",
        )


class IntervalRecordType(DjangoObjectType):
    batch = graphene.Field(IngestionBatchType, required=True)

    class Meta:
        model = IntervalRecord
        fields = ("id", "value", "quality", "method_code", "interval_end_utc")


class QuarantinedIntervalType(DjangoObjectType):
    channel = graphene.Field(MeterChannelType, required=True)
    candidate_records = graphene.List(IntervalRecordType, required=True)

    class Meta:
        model = QuarantinedInterval
        fields = ("id", "interval_end_utc", "status", "detail", "created_at")

    def resolve_candidate_records(quarantine, info):
        return quarantine.candidate_records.all()


class CurrentIntervalType(DjangoObjectType):
    class Meta:
        model = CurrentInterval
        fields = ("interval_end_utc", "value", "quality", "selection_version")


class RatingLineType(graphene.ObjectType):
    """Calculation line item — a RatingRun line or a pinned legacy
    response line, both attribute-compatible."""

    sequence = graphene.Int()
    tariff_code = graphene.String()
    element = graphene.String()
    band = graphene.String()
    quantity = graphene.Decimal()
    unit = graphene.String()
    rate = graphene.Decimal()
    amount = graphene.Decimal()
    gst = graphene.Decimal()
    basis = graphene.String()
    segment_from = graphene.Date()
    segment_to = graphene.Date()


class RatingRunType(graphene.ObjectType):
    """The pinned calculation evidence behind an invoice or rating
    result — a persisted RatingRun, or an authoritative legacy
    calculation presented in the same shape."""

    id = graphene.Int()
    period_start = graphene.Date()
    period_end = graphene.Date()
    net = graphene.Decimal()
    gst = graphene.Decimal()
    total = graphene.Decimal()
    input_digest = graphene.String()
    engine_version = graphene.String()
    policy_identity = graphene.String()
    created_at = graphene.DateTime()
    lines = graphene.List(RatingLineType, required=True)

    def resolve_lines(run, info):
        # Real RatingRun queryset vs. legacy evidence namespaces (below).
        lines = run.lines
        return lines.order_by("sequence") if hasattr(lines, "order_by") else lines


class PostingType(DjangoObjectType):
    class Meta:
        model = Posting
        fields = ("account_code", "debit", "credit", "memo")


class AdjustmentType(DjangoObjectType):
    class Meta:
        model = Adjustment
        fields = (
            "number",
            "generation",
            "input_digest",
            "delta_charge",
            "delta_export",
            "delta_gst",
            "delta_total",
            "issued_at",
        )


class JournalEntryType(DjangoObjectType):
    postings = graphene.List(PostingType, required=True)
    adjustment = graphene.Field(AdjustmentType)

    class Meta:
        model = JournalEntry
        fields = ("id", "memo", "posted_at")

    def resolve_postings(journal, info):
        return journal.postings.all()


class InvoiceType(DjangoObjectType):
    journal_entries = graphene.List(JournalEntryType, required=True)
    adjustments = graphene.List(AdjustmentType, required=True)
    rating_run = graphene.Field(RatingRunType, required=True)

    class Meta:
        model = Invoice
        fields = (
            "number",
            "period_start",
            "period_end",
            "net",
            "gst",
            "total",
            "input_digest",
            "calculation_source",
            "issued_at",
        )

    def resolve_journal_entries(invoice, info):
        return invoice.journal_entries.all()

    def resolve_adjustments(invoice, info):
        return invoice.adjustments.order_by("generation")

    def resolve_rating_run(invoice, info):
        # The pinned *authoritative* calculation: a Taryx run for
        # new-source invoices, the persisted legacy response for
        # legacy-source ones — its line items reconcile to the invoice.
        if invoice.calculation_source != "legacy":
            return invoice.rating_run
        return _legacy_evidence(invoice)


def _legacy_line(item: dict, sequence: int) -> SimpleNamespace:
    return SimpleNamespace(
        sequence=sequence,
        tariff_code=item["tariff_code"],
        element=item["element"],
        band=item.get("band"),
        quantity=Decimal(str(item["quantity"])),
        unit=item["unit"],
        rate=Decimal(str(item["rate"])),
        amount=Decimal(str(item["amount"])),
        gst=Decimal(str(item["gst"])),
        basis=item.get("basis", ""),
        segment_from=date.fromisoformat(item["segment_from"]),
        segment_to=date.fromisoformat(item["segment_to"]),
    )


def _legacy_evidence(invoice: Invoice) -> SimpleNamespace:
    """Authoritative legacy calculation presented in RatingRun shape."""
    calc = None
    if invoice.legacy_calculation_id:
        calc = (
            LegacyCalculation.objects.using(SHADOW_ALIAS)
            .filter(pk=invoice.legacy_calculation_id)
            .first()
        )
    if calc is not None:
        return SimpleNamespace(
            id=calc.id,
            period_start=invoice.period_start,
            period_end=invoice.period_end,
            net=calc.net,
            gst=calc.gst,
            total=calc.total,
            input_digest=calc.snapshot_hash,
            engine_version=calc.engine_version,
            policy_identity=f"legacy catalogue {calc.catalogue_version}",
            created_at=calc.received_at,
            lines=[
                _legacy_line(item, i + 1)
                for i, item in enumerate(calc.response_json.get("lines", []))
            ],
        )
    # No pinned response (e.g. synthetic calculator): reconcile to the
    # invoice totals with an explicitly labelled aggregate line rather
    # than presenting the new-engine comparison run as authoritative.
    return SimpleNamespace(
        id=None,
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        net=invoice.net,
        gst=invoice.gst,
        total=invoice.total,
        input_digest=invoice.input_digest,
        engine_version="legacy",
        policy_identity=None,
        created_at=invoice.issued_at,
        lines=[
            SimpleNamespace(
                sequence=1,
                tariff_code="legacy",
                element="authoritative_total",
                band=None,
                quantity=Decimal(1),
                unit="bill",
                rate=invoice.net,
                amount=invoice.net,
                gst=invoice.gst,
                basis="legacy authoritative totals — line detail not pinned",
                segment_from=invoice.period_start,
                segment_to=invoice.period_end,
            )
        ],
    )


class BillingOperationType(DjangoObjectType):
    invoice = graphene.Field(InvoiceType)
    adjustment = graphene.Field(AdjustmentType)

    class Meta:
        model = BillingOperation
        fields = (
            "operation_id",
            "status",
            "detail",
            "period_start",
            "period_end",
            "created_at",
            "completed_at",
        )


class MarketInboxType(graphene.ObjectType):
    correlation_id = graphene.String(required=True)
    seq = graphene.Int(required=True)
    outcome = graphene.String(required=True)
    note = graphene.String(required=True)
    received_at = graphene.DateTime(required=True)


class TransferWorkflowType(DjangoObjectType):
    correlation_id = graphene.String(required=True)
    nmi = graphene.String(required=True)
    inbox = graphene.List(MarketInboxType, required=True)

    class Meta:
        model = TransferWorkflow
        fields = (
            "state",
            "effective_date",
            "request_digest",
            "last_applied_seq",
            "attempts",
            "deadline_at",
            "last_counterparty_status",
            "detail",
            "created_at",
        )

    def resolve_correlation_id(workflow, info):
        return str(workflow.correlation_id)

    def resolve_nmi(workflow, info):
        return workflow.supply_point.nmi

    def resolve_inbox(workflow, info):
        return workflow.inbox.order_by("received_at")


class MarketExceptionType(DjangoObjectType):
    correlation_id = graphene.String()

    class Meta:
        model = MarketException
        fields = ("reason", "raw", "created_at")

    def resolve_correlation_id(exc, info):
        return str(exc.correlation_id) if exc.correlation_id else None


class DecisionType(graphene.ObjectType):
    fingerprint = graphene.String(required=True)
    classification = graphene.String(required=True)
    actor = graphene.String()
    reason = graphene.String()
    # Whether the decision still pins the latest cohort evidence carrying
    # its fingerprint — stale decisions need re-approval, not reuse.
    valid = graphene.Boolean(required=True)


class CohortType(DjangoObjectType):
    members = graphene.List(AccountType, required=True)
    blockers = graphene.List(graphene.String, required=True)
    decisions = graphene.List(DecisionType, required=True)

    class Meta:
        model = Cohort
        fields = (
            "id",
            "name",
            "routing_mode",
            "routing_revision",
            "eval_period_start",
            "eval_period_end",
            "eval_frozen_at",
        )

    def resolve_members(cohort, info):
        return cohort.members.all()

    def resolve_blockers(cohort, info):
        return evaluation_blockers(cohort, **_policy_kwargs())

    def resolve_decisions(cohort, info):
        evidence = list(
            ComparisonRun.objects.using(SHADOW_ALIAS)
            .filter(
                account__in=cohort.members.all(),
                period_start=cohort.eval_period_start,
                period_end=cohort.eval_period_end,
            )
            .order_by("-updated_at")
        )

        def valid(d) -> bool:
            carrier = next(
                (
                    c
                    for c in evidence
                    if any(
                        x["fingerprint"] == d.fingerprint for x in c.report_json.get("diffs", [])
                    )
                ),
                None,
            )
            return carrier is not None and d.is_valid_for(carrier)

        return [
            DecisionType(
                fingerprint=d.fingerprint,
                classification=d.classification,
                actor=d.actor.username,
                reason=d.reason,
                valid=valid(d),
            )
            for d in cohort.discrepancydecision_set.order_by("created_at")
        ]


class ComparisonRunType(DjangoObjectType):
    account = graphene.Field(AccountType, required=True)
    report = graphene.JSONString()

    class Meta:
        model = ComparisonRun
        fields = (
            "id",
            "period_start",
            "period_end",
            "snapshot_hash",
            "new_engine_version",
            "legacy_version_token",
            "policy_identity",
            "status",
            "failure_code",
            "created_at",
        )

    def resolve_report(row, info):
        return row.report_json


class CohortEventType(DjangoObjectType):
    actor = graphene.String()

    class Meta:
        model = CohortEvent
        fields = (
            "id",
            "action",
            "from_mode",
            "to_mode",
            "routing_revision",
            "detail",
            "created_at",
        )

    def resolve_actor(event, info):
        return event.actor.username if event.actor else None


class UserType(graphene.ObjectType):
    username = graphene.String(required=True)
    role = graphene.String()


class Query(graphene.ObjectType):
    ping = graphene.String(required=True)
    version = graphene.String(required=True)
    client_name = graphene.String(required=True)
    me = graphene.Field(UserType)
    accounts = graphene.List(AccountType, required=True, limit=graphene.Int(default_value=50))
    account = graphene.Field(AccountType, reference=graphene.String(required=True))
    ingestion_batches = graphene.List(
        IngestionBatchType,
        required=True,
        status=graphene.String(),
        limit=graphene.Int(default_value=50),
    )
    quarantined_intervals = graphene.List(
        QuarantinedIntervalType,
        required=True,
        status=graphene.String(default_value="open"),
        limit=graphene.Int(default_value=50),
    )
    current_intervals = graphene.List(
        CurrentIntervalType,
        required=True,
        channel_id=graphene.Int(required=True),
        day=graphene.Date(required=True),
    )
    rating_runs = graphene.List(
        RatingRunType,
        required=True,
        reference=graphene.String(required=True),
        limit=graphene.Int(default_value=20),
    )
    invoices = graphene.List(
        InvoiceType,
        required=True,
        reference=graphene.String(required=True),
        limit=graphene.Int(default_value=20),
    )
    invoice = graphene.Field(InvoiceType, number=graphene.String(required=True))
    billing_operation = graphene.Field(
        BillingOperationType, operation_id=graphene.String(required=True)
    )

    cohorts = graphene.List(CohortType, required=True)
    comparisons = graphene.List(ComparisonRunType, required=True, account_ref=graphene.String())
    cohort_events = graphene.List(
        CohortEventType, required=True, cohort_id=graphene.Int(required=True)
    )

    market_workflows = graphene.List(
        TransferWorkflowType, required=True, limit=graphene.Int(default_value=50)
    )
    market_workflow = graphene.Field(
        TransferWorkflowType, correlation_id=graphene.String(required=True)
    )
    market_exceptions = graphene.List(
        MarketExceptionType, required=True, limit=graphene.Int(default_value=50)
    )

    def resolve_cohorts(root, info):
        _require_auth(info)
        return Cohort.objects.order_by("name")

    def resolve_comparisons(root, info, account_ref=None):
        _require_auth(info)
        qs = ComparisonRun.objects.using(SHADOW_ALIAS).order_by("-created_at")[:50]
        if account_ref:
            return [c for c in qs if c.account.reference == account_ref]
        return list(qs)

    def resolve_cohort_events(root, info, cohort_id):
        _require_auth(info)
        return CohortEvent.objects.filter(cohort_id=cohort_id).order_by("-created_at")[:50]

    def resolve_market_workflows(root, info, limit=50):
        _require_auth(info)
        return _bounded(TransferWorkflow.objects.order_by("-created_at"), limit)

    def resolve_market_workflow(root, info, correlation_id):
        _require_auth(info)
        return TransferWorkflow.objects.filter(correlation_id=correlation_id).first()

    def resolve_market_exceptions(root, info, limit=50):
        _require_auth(info)
        return _bounded(MarketException.objects.order_by("-created_at"), limit)

    def resolve_ping(root, info):
        return "pong"

    def resolve_version(root, info):
        return "0.1.0"

    def resolve_client_name(root, info):
        return _policy().CLIENT_NAME

    def resolve_me(root, info):
        user = _user(info)
        if user is None:
            return None
        return UserType(username=user.username, role=_role(user))

    def resolve_accounts(root, info, limit):
        _require_auth(info)
        return _bounded(Account.objects.order_by("reference"), limit)

    def resolve_account(root, info, reference):
        _require_auth(info)
        return Account.objects.filter(reference=reference).first()

    def resolve_ingestion_batches(root, info, status=None, limit=50):
        _require_auth(info)
        qs = IngestionBatch.objects.order_by("-received_at", "-id")
        if status:
            qs = qs.filter(status=status)
        return _bounded(qs, limit)

    def resolve_quarantined_intervals(root, info, status="open", limit=50):
        _require_auth(info)
        return _bounded(
            QuarantinedInterval.objects.filter(status=status).order_by("-created_at"), limit
        )

    def resolve_current_intervals(root, info, channel_id, day):
        _require_auth(info)
        channel = MeterChannel.objects.filter(pk=channel_id).first()
        if channel is None:
            return []
        start = nem_interval_end_utc(day, 0, channel.interval_minutes)
        end = nem_interval_end_utc(day + timedelta(days=1), 0, channel.interval_minutes)
        return CurrentInterval.objects.filter(
            channel_id=channel_id,
            interval_end_utc__gt=start,
            interval_end_utc__lte=end,
        ).order_by("interval_end_utc")[:MAX_LIMIT]

    def resolve_rating_runs(root, info, reference, limit=20):
        _require_auth(info)
        return _bounded(
            RatingRun.objects.filter(account__reference=reference).order_by("-id"), limit
        )

    def resolve_invoices(root, info, reference, limit=20):
        _require_auth(info)
        return _bounded(
            Invoice.objects.filter(account__reference=reference).order_by("-issued_at"),
            limit,
        )

    def resolve_invoice(root, info, number):
        _require_auth(info)
        return Invoice.objects.filter(number=number).first()

    def resolve_billing_operation(root, info, operation_id):
        _require_auth(info)
        return BillingOperation.objects.filter(operation_id=operation_id).first()


class LoginPayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)
    code = graphene.String()
    user = graphene.Field(UserType)


class Login(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        password = graphene.String(required=True)

    Output = LoginPayload

    def mutate(root, info, username, password):
        user = authenticate(info.context, username=username, password=password)
        if user is None:
            return LoginPayload(ok=False, code="invalid_credentials")
        login(info.context, user)
        return LoginPayload(ok=True, user=UserType(username=user.username, role=_role(user)))


class LogoutPayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)


class Logout(graphene.Mutation):
    Output = LogoutPayload

    def mutate(root, info):
        logout(info.context)
        return LogoutPayload(ok=True)


class IngestPayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)
    code = graphene.String()
    batch = graphene.Field(IngestionBatchType)


class IngestNem12(graphene.Mutation):
    class Arguments:
        filename = graphene.String(required=True)
        content = graphene.String(required=True)

    Output = IngestPayload

    def mutate(root, info, filename, content):
        _require_group(info, "operator")
        result = ingest_nem12_content(content.encode("utf-8"), filename)
        batch = result.batch
        audit_record(
            _actor(info),
            "metering.ingest",
            filename,
            status=batch.status,
            error_code=batch.error_code,
        )
        return IngestPayload(ok=True, code=batch.error_code, batch=batch)


class RatePayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)
    code = graphene.String()
    message = graphene.String()
    run = graphene.Field(RatingRunType)


class RateAccount(graphene.Mutation):
    class Arguments:
        reference = graphene.String(required=True)
        period_start = graphene.Date(required=True)
        period_end = graphene.Date(required=True)

    Output = RatePayload

    def mutate(root, info, reference, period_start, period_end):
        _require_group(info, "operator")
        account = Account.objects.filter(reference=reference).first()
        if account is None:
            return RatePayload(ok=False, code="not_found", message="unknown account")
        try:
            run = rate_account(account, period_start, period_end, **_policy_kwargs())
        except RatingError as exc:
            return RatePayload(ok=False, code=exc.code, message=str(exc))
        audit_record(
            _actor(info),
            "pricing.rate",
            reference,
            run_id=run.id,
            total=str(run.total),
            period=f"{period_start}..{period_end}",
        )
        return RatePayload(ok=True, run=run)


class BillPayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)
    code = graphene.String()
    message = graphene.String()
    operation = graphene.Field(BillingOperationType)


class BillAccount(graphene.Mutation):
    class Arguments:
        reference = graphene.String(required=True)
        period_start = graphene.Date(required=True)
        period_end = graphene.Date(required=True)
        operation_id = graphene.String(required=True)

    Output = BillPayload

    def mutate(root, info, reference, period_start, period_end, operation_id):
        _require_group(info, "operator")
        account = Account.objects.filter(reference=reference).first()
        if account is None:
            return BillPayload(ok=False, code="not_found", message="unknown account")
        existing = BillingOperation.objects.filter(operation_id=operation_id).first()
        if existing is not None:
            # Retry recovery: the public request (account/period) is what
            # the caller committed to; a newer rating run must not turn an
            # identical retry into a payload conflict.
            if (
                existing.account_id != account.id
                or existing.period_start != period_start
                or existing.period_end != period_end
            ):
                return BillPayload(
                    ok=False,
                    code="operation_conflict",
                    message=(
                        f"operation {operation_id!r} was admitted for a different account or period"
                    ),
                )
            return BillPayload(ok=True, operation=existing)
        run = (
            RatingRun.objects.filter(
                account=account, period_start=period_start, period_end=period_end
            )
            .order_by("-id")
            .first()
        )
        if run is None:
            return BillPayload(ok=False, code="no_rating_run", message="rate first")
        try:
            op = admit_issue(
                account,
                period_start,
                period_end,
                run,
                operation_id,
                routing_resolver=routing_for,
            )
        except AdmissionError as exc:
            return BillPayload(ok=False, code=exc.code, message=str(exc))
        audit_record(
            _actor(info),
            "billing.admit",
            reference,
            operation_id=operation_id,
            rating_run_id=run.id,
        )
        with suppress(Exception):  # broker down: outbox retains pending work
            process_billing_operation.delay(op.operation_id)
        return BillPayload(ok=True, operation=op)


class ResolvePayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)
    code = graphene.String()
    message = graphene.String()
    quarantine = graphene.Field(QuarantinedIntervalType)


class ResolveQuarantine(graphene.Mutation):
    class Arguments:
        quarantine_id = graphene.Int(required=True)
        record_id = graphene.Int(required=True)
        reason = graphene.String(required=True)

    Output = ResolvePayload

    def mutate(root, info, quarantine_id, record_id, reason):
        _require_group(info, "approver")
        try:
            quarantine = resolve_quarantine(
                quarantine_id, record_id, actor=_actor(info), reason=reason
            )
        except ResolutionError as exc:
            return ResolvePayload(ok=False, code=exc.code, message=str(exc))
        audit_record(
            _actor(info),
            "metering.resolve_quarantine",
            str(quarantine_id),
            record_id=record_id,
            reason=reason,
        )
        return ResolvePayload(ok=True, quarantine=quarantine)


class ShadowPayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)
    code = graphene.String()
    message = graphene.String()
    comparison = graphene.Field(ComparisonRunType)


class RunShadowComparison(graphene.Mutation):
    class Arguments:
        reference = graphene.String(required=True)
        period_start = graphene.Date(required=True)
        period_end = graphene.Date(required=True)

    Output = ShadowPayload

    def mutate(root, info, reference, period_start, period_end):
        _require_group(info, "operator", "approver")
        account = Account.objects.filter(reference=reference).first()
        if account is None:
            return ShadowPayload(ok=False, code="not_found", message="unknown account")
        run = (
            RatingRun.objects.filter(
                account=account, period_start=period_start, period_end=period_end
            )
            .order_by("-id")
            .first()
        )
        if run is None:
            return ShadowPayload(ok=False, code="no_rating_run", message="rate first")
        row = run_comparison(run)
        audit_record(
            _actor(info),
            "migration.compare",
            reference,
            comparison_id=row.id,
            status=row.status,
        )
        return ShadowPayload(ok=True, comparison=row)


class DecidePayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)
    code = graphene.String()
    message = graphene.String()


class DecideDiscrepancy(graphene.Mutation):
    class Arguments:
        cohort_id = graphene.Int(required=True)
        fingerprint = graphene.String(required=True)
        classification = graphene.String(required=True)
        reason = graphene.String(required=True)

    Output = DecidePayload

    def mutate(root, info, cohort_id, fingerprint, classification, reason):
        _require_group(info, "operator", "approver")
        cohort = Cohort.objects.filter(pk=cohort_id).first()
        if cohort is None:
            return DecidePayload(ok=False, code="not_found", message="unknown cohort")
        try:
            decide_discrepancy(
                cohort=cohort,
                fingerprint=fingerprint,
                classification=classification,
                actor=_user(info),
                reason=reason,
            )
        except MigrationError as exc:
            return DecidePayload(ok=False, code=exc.code, message=str(exc))
        audit_record(
            _actor(info),
            "migration.decision",
            f"cohort:{cohort_id}",
            fingerprint=fingerprint,
            classification=classification,
        )
        return DecidePayload(ok=True)


class TransitionPayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)
    code = graphene.String()
    message = graphene.String()
    cohort = graphene.Field(CohortType)


class TransitionCohort(graphene.Mutation):
    class Arguments:
        cohort_id = graphene.Int(required=True)
        to_mode = graphene.String(required=True)
        expected_revision = graphene.Int(required=True)
        reason = graphene.String()

    Output = TransitionPayload

    def mutate(root, info, cohort_id, to_mode, expected_revision, reason=None):
        _require_group(info, "approver")
        try:
            cohort = transition_cohort(
                cohort_id,
                to_mode,
                expected_revision,
                _user(info),
                reason=reason or "",
                **_policy_kwargs(),
            )
        except MigrationError as exc:
            return TransitionPayload(ok=False, code=exc.code, message=str(exc))
        audit_record(
            _actor(info),
            "migration.transition",
            f"cohort:{cohort_id}",
            to_mode=to_mode,
            revision=cohort.routing_revision,
        )
        return TransitionPayload(ok=True, cohort=cohort)


class TransferPayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)
    code = graphene.String()
    message = graphene.String()
    workflow = graphene.Field(TransferWorkflowType)


class RequestTransfer(graphene.Mutation):
    """Admit a synthetic taryx-market/1 transfer request durably and
    kick the submit task; the workflow is the idempotency boundary —
    one correlation per row, retries resume it."""

    class Arguments:
        nmi = graphene.String(required=True)
        effective_date = graphene.Date(required=True)

    Output = TransferPayload

    def mutate(root, info, nmi, effective_date):
        _require_group(info, "operator")
        supply_point = SupplyPoint.objects.filter(nmi=nmi).first()
        if supply_point is None:
            return TransferPayload(ok=False, code="not_found", message="unknown NMI")
        workflow = request_transfer(supply_point, effective_date)
        market_submit.delay(str(workflow.correlation_id))
        audit_record(
            _actor(info),
            "market.transfer_request",
            nmi,
            correlation_id=str(workflow.correlation_id),
        )
        return TransferPayload(ok=True, workflow=workflow)


class Mutation(graphene.ObjectType):
    login = Login.Field()
    logout = Logout.Field()
    ingest_nem12 = IngestNem12.Field()
    rate_account = RateAccount.Field()
    bill_account = BillAccount.Field()
    resolve_quarantine = ResolveQuarantine.Field()
    run_shadow_comparison = RunShadowComparison.Field()
    decide_discrepancy = DecideDiscrepancy.Field()
    transition_cohort = TransitionCohort.Field()
    request_transfer = RequestTransfer.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)
