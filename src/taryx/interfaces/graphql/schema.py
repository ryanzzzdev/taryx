"""Bounded operator GraphQL contract (decision 004).

Session-authenticated; role groups viewer/operator/approver are enforced
server-side here. Mutations return payload objects with stable `code`
values instead of throwing GraphQL errors for domain failures, so the
portal renders outcomes deterministically and can poll operations.
"""

from contextlib import suppress
from datetime import timedelta

import graphene
from django.contrib.auth import authenticate, login, logout
from graphene_django import DjangoObjectType
from graphql import GraphQLError

from taryx.composition.tasks import process_billing_operation
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
from taryx.core.pricing.engine import RatingError
from taryx.core.pricing.models import RatingLine, RatingRun
from taryx.core.pricing.services import rate_account
from taryx.territories.au_nem.tariffs import GST_RATE, POLICY_IDENTITY, TARIFFS

MAX_LIMIT = 200


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


class RatingLineType(DjangoObjectType):
    class Meta:
        model = RatingLine
        fields = (
            "sequence",
            "tariff_code",
            "element",
            "band",
            "quantity",
            "unit",
            "rate",
            "amount",
            "gst",
            "basis",
            "segment_from",
            "segment_to",
        )


class RatingRunType(DjangoObjectType):
    lines = graphene.List(RatingLineType, required=True)

    class Meta:
        model = RatingRun
        fields = (
            "id",
            "period_start",
            "period_end",
            "net",
            "gst",
            "total",
            "input_digest",
            "engine_version",
            "policy_identity",
            "created_at",
        )

    def resolve_lines(run, info):
        return run.lines.order_by("sequence")


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
            "issued_at",
        )

    def resolve_journal_entries(invoice, info):
        return invoice.journal_entries.all()

    def resolve_adjustments(invoice, info):
        return invoice.adjustments.order_by("generation")


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


class UserType(graphene.ObjectType):
    username = graphene.String(required=True)
    role = graphene.String()


class Query(graphene.ObjectType):
    ping = graphene.String(required=True)
    version = graphene.String(required=True)
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

    def resolve_ping(root, info):
        return "pong"

    def resolve_version(root, info):
        return "0.1.0"

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
            run = rate_account(
                account,
                period_start,
                period_end,
                tariffs=TARIFFS,
                gst_rate=GST_RATE,
                policy_identity=POLICY_IDENTITY,
            )
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
            op = admit_issue(account, period_start, period_end, run, operation_id)
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


class Mutation(graphene.ObjectType):
    login = Login.Field()
    logout = Logout.Field()
    ingest_nem12 = IngestNem12.Field()
    rate_account = RateAccount.Field()
    bill_account = BillAccount.Field()
    resolve_quarantine = ResolveQuarantine.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)
