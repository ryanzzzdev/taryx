"""Comparison runner, cutover gate evaluation and cohort transitions.

Evidence writes go through the `shadow` database alias: the role behind
it is granted only SELECT plus migration_* table writes, so the database
itself rejects any financial write attempted from a shadow code path.
"""

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from taryx.core.accounts.models import Account
from taryx.core.billing.models import BillingOperation
from taryx.core.migration import comparison
from taryx.core.migration.legacy_adapter import (
    LegacyFailure,
    build_request,
    calculate,
)
from taryx.core.migration.models import (
    SHADOW_ALIAS,
    Cohort,
    CohortEvent,
    ComparisonRun,
    DiscrepancyDecision,
    LegacyCalculation,
)
from taryx.core.pricing.models import RatingRun
from taryx.core.pricing.services import compute_input_digest
from taryx.core.pricing.tariffs import TariffSpec

ALLOWED_TRANSITIONS = {
    (Cohort.Mode.LEGACY_ONLY, Cohort.Mode.SHADOW),
    (Cohort.Mode.SHADOW, Cohort.Mode.NEW_ONLY),
    (Cohort.Mode.LEGACY_ONLY, Cohort.Mode.NEW_ONLY),
    (Cohort.Mode.SHADOW, Cohort.Mode.LEGACY_ONLY),
    (Cohort.Mode.NEW_ONLY, Cohort.Mode.LEGACY_ONLY),
}


class MigrationError(Exception):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


def run_comparison(rating_run: RatingRun, *, base_url: str | None = None) -> ComparisonRun:
    """Call legacy for the run's snapshot and persist comparison evidence.

    Inconclusive outcomes (timeout/malformed/unavailable/version) are
    persisted as INCONCLUSIVE evidence — they block cutover, they are
    never parity. Evidence rows are written under the shadow alias.
    """
    account = rating_run.account
    request = build_request(rating_run.input_snapshot, rating_run.input_digest)
    url = base_url or settings.LEGACY_BASE_URL
    try:
        result = calculate(request, base_url=url, timeout=settings.LEGACY_TIMEOUT_SECONDS)
    except LegacyFailure as exc:
        with transaction.atomic(using=SHADOW_ALIAS):
            run_row, _ = ComparisonRun.objects.using(SHADOW_ALIAS).update_or_create(
                snapshot_hash=rating_run.input_digest,
                legacy_version_token="unavailable",
                defaults={
                    "account_id": account.id,
                    "period_start": rating_run.period_start,
                    "period_end": rating_run.period_end,
                    "rating_run_id": rating_run.id,
                    "legacy_calculation_id": None,
                    "new_engine_version": rating_run.engine_version,
                    "policy_identity": rating_run.policy_identity,
                    "status": ComparisonRun.Status.INCONCLUSIVE,
                    "failure_code": exc.code,
                    "report_json": {"status": "inconclusive", "failure_code": exc.code},
                    "created_at": timezone.now(),
                },
            )
        return run_row

    return _persist_comparison(rating_run, result)


def routing_for(account: Account) -> tuple[str, int]:
    """The authoritative routing mode + revision for an account.

    Accounts in no cohort are on the new engine already."""
    cohort = Cohort.objects.filter(members=account).first()
    if cohort is None:
        return ("new_only", 0)
    return (cohort.routing_mode, cohort.routing_revision)


def calculate_for_billing(op, *, base_url: str | None = None) -> dict:
    """Legacy-authoritative amounts for a billing operation.

    Under SHADOW the same response also feeds a persisted comparison —
    the new engine's run is the comparison subject, the legacy result
    is the authoritative amount basis.
    """
    rating_run = op.rating_run
    request = build_request(rating_run.input_snapshot, rating_run.input_digest)
    result = calculate(
        request,
        base_url=base_url or settings.LEGACY_BASE_URL,
        timeout=settings.LEGACY_TIMEOUT_SECONDS,
    )
    _persist_legacy_result(result)
    if op.cohort_mode == Cohort.Mode.SHADOW:
        _persist_comparison(rating_run, result)
    return {
        "charge": sum(
            (line.amount for line in result.lines if line.element in {"import", "supply"}),
            Decimal(0),
        ),
        "export": -sum(
            (line.amount for line in result.lines if line.element == "export_credit"),
            Decimal(0),
        ),
        "gst": result.gst,
        "net": result.net,
        "total": result.total,
    }


def _persist_comparison(rating_run: RatingRun, result) -> ComparisonRun:
    account = rating_run.account
    legacy_calc = _persist_legacy_result(result)
    data = comparison.report(rating_run, result, account.reference)
    with transaction.atomic(using=SHADOW_ALIAS):
        # Re-verified success updates the stable comparison identity and
        # bumps updated_at — an intervening failed attempt is retained but
        # no longer the latest conclusive observation.
        row, _ = ComparisonRun.objects.using(SHADOW_ALIAS).update_or_create(
            snapshot_hash=rating_run.input_digest,
            legacy_version_token=result.version_token,
            defaults={
                "account_id": account.id,
                "period_start": rating_run.period_start,
                "period_end": rating_run.period_end,
                "rating_run_id": rating_run.id,
                "legacy_calculation_id": legacy_calc.id,
                "new_engine_version": rating_run.engine_version,
                "policy_identity": rating_run.policy_identity,
                "status": data["status"],
                "failure_code": None,
                "report_json": data,
            },
        )
    return row


def _persist_legacy_result(result) -> LegacyCalculation:
    with transaction.atomic(using=SHADOW_ALIAS):
        row, _ = LegacyCalculation.objects.using(SHADOW_ALIAS).get_or_create(
            snapshot_hash=result.snapshot_hash,
            engine_version=result.engine_version,
            catalogue_version=result.catalogue_version,
            defaults={
                "request_id": result.request_id,
                "response_json": {
                    "lines": [
                        {
                            **vars(line),
                            "segment_from": line.segment_from.isoformat(),
                            "segment_to": line.segment_to.isoformat(),
                            "quantity": str(line.quantity),
                            "rate": str(line.rate),
                            "amount": str(line.amount),
                            "gst": str(line.gst),
                        }
                        for line in result.lines
                    ],
                    "net": str(result.net),
                    "gst": str(result.gst),
                    "total": str(result.total),
                },
                "net": result.net,
                "gst": result.gst,
                "total": result.total,
            },
        )
    return row


def evaluation_blockers(
    cohort: Cohort,
    *,
    tariffs: dict[str, TariffSpec],
    gst_rate: Decimal,
    policy_identity: str,
) -> list[str]:
    """Frozen gate rules for a cohort's declared evaluation set.

    Freshness: evidence must postdate eval_frozen_at, pin the *current*
    input digest and current engine/policy versions, and be conclusive.
    Every difference needs a still-valid scoped decision.
    """
    blockers: list[str] = []
    members = list(cohort.members.all())
    if not members:
        return ["empty_cohort: no member accounts"]
    for account in members:
        comparisons = list(
            ComparisonRun.objects.using(SHADOW_ALIAS)
            .filter(
                account=account,
                period_start=cohort.eval_period_start,
                period_end=cohort.eval_period_end,
            )
            .order_by("-updated_at")
        )
        ref = f"{account.reference}"
        if not comparisons:
            blockers.append(f"missing_evidence: no comparison for {ref}")
            continue
        # Latest observation of ANY status governs: a failed attempt
        # after the last success blocks until a re-verified success
        # (which refreshes updated_at) supersedes it.
        latest = comparisons[0]
        if latest.status == ComparisonRun.Status.INCONCLUSIVE:
            blockers.append(f"inconclusive: {ref} comparison failed ({latest.failure_code})")
            continue
        if latest.updated_at < cohort.eval_frozen_at:
            blockers.append(f"stale_window: {ref} evidence predates the freeze")
            continue
        current_digest = compute_input_digest(
            account,
            cohort.eval_period_start,
            cohort.eval_period_end,
            tariffs=tariffs,
            gst_rate=gst_rate,
            policy_identity=policy_identity,
        )
        if latest.snapshot_hash != current_digest:
            blockers.append(f"stale_evidence: {ref} inputs changed since comparison")
            continue
        if latest.policy_identity != policy_identity:
            blockers.append(f"stale_policy: {ref} evidence predates {policy_identity}")
            continue
        latest_diffs = {d["fingerprint"] for d in latest.report_json.get("diffs", [])}
        decided = {
            d.fingerprint: d.classification
            for d in DiscrepancyDecision.objects.using(SHADOW_ALIAS).filter(cohort=cohort)
            if d.is_valid_for(latest)
        }
        for fp in sorted(latest_diffs):
            classification = decided.get(fp)
            if classification is None:
                blockers.append(f"unresolved_difference: {ref} {fp[:12]}")
            elif classification == DiscrepancyDecision.Classification.PRESERVE_CLIENT_POLICY:
                # A preserved policy must be implemented by the new
                # engine — evidenced by the fingerprint no longer
                # appearing. A still-present difference means the policy
                # would be dropped by cutover.
                blockers.append(f"unpreserved_policy: {ref} {fp[:12]}")
        # A preserve decision whose fingerprint is absent from the latest
        # diffs is satisfied: the new engine now produces the preserved
        # behaviour, evidenced by the difference disappearing.
    return blockers


def transition_cohort(
    cohort_id: int,
    to_mode: str,
    expected_revision: int,
    actor,
    reason: str = "",
    *,
    tariffs: dict[str, TariffSpec],
    gst_rate: Decimal,
    policy_identity: str,
) -> Cohort:
    """Move a cohort between routing modes under guards.

    Guards: optimistic revision check, no in-flight billing operations
    for member accounts, legal transition edge, and the frozen cutover
    gate for any move to NEW_ONLY.
    """
    with transaction.atomic():
        cohort = Cohort.objects.select_for_update().filter(pk=cohort_id).first()
        if cohort is None:
            raise MigrationError("not_found", "no such cohort")
        if cohort.routing_revision != expected_revision:
            raise MigrationError(
                "stale_revision",
                f"expected r{expected_revision}, actual r{cohort.routing_revision}",
            )
        in_flight = BillingOperation.objects.filter(
            account__in=cohort.members.all(), status=BillingOperation.Status.PENDING
        ).exists()
        if in_flight:
            raise MigrationError("in_flight", "pending billing operations exist for cohort members")
        edge = (cohort.routing_mode, to_mode)
        if edge not in ALLOWED_TRANSITIONS:
            raise MigrationError("invalid_transition", f"{edge[0]} -> {edge[1]}")
        if to_mode == Cohort.Mode.NEW_ONLY:
            blockers = evaluation_blockers(
                cohort,
                tariffs=tariffs,
                gst_rate=gst_rate,
                policy_identity=policy_identity,
            )
            if blockers:
                raise MigrationError("gate_blocked", "; ".join(blockers))
            # Commit-safe revalidation: lock every member account row,
            # then re-run the COMPLETE gate and the in-flight check.
            # Inputs, comparisons, decisions or ops committed during the
            # first evaluation are now visible (stale → reject); ones
            # still in flight block on the account lock and can only
            # commit after this transaction — i.e. after cutover.
            members = list(Account.objects.filter(cohort=cohort).order_by("pk").select_for_update())
            blockers = evaluation_blockers(
                cohort,
                tariffs=tariffs,
                gst_rate=gst_rate,
                policy_identity=policy_identity,
            )
            if blockers:
                raise MigrationError(
                    "gate_blocked",
                    "revalidation under commit locks: " + "; ".join(blockers),
                )
            if BillingOperation.objects.filter(
                account__in=members, status=BillingOperation.Status.PENDING
            ).exists():
                raise MigrationError("in_flight", "billing admitted during gate evaluation")
        cohort.routing_mode = to_mode
        cohort.routing_revision += 1
        cohort.save(update_fields=["routing_mode", "routing_revision"])
        CohortEvent.objects.create(
            cohort=cohort,
            actor=actor,
            action="transition",
            from_mode=edge[0],
            to_mode=to_mode,
            routing_revision=cohort.routing_revision,
            detail={"reason": reason},
        )
    return cohort


def decide_discrepancy(
    *, cohort: Cohort, fingerprint: str, classification: str, actor, reason: str
) -> DiscrepancyDecision:
    """Record a scoped decision for one diff fingerprint.

    The decision pins the versions and snapshot hash of the latest cohort
    evidence carrying that fingerprint — it cannot bless a difference it
    never saw, nor carry forward to changed inputs or engines.
    """
    if classification not in DiscrepancyDecision.Classification.values:
        raise MigrationError("bad_classification", f"unknown classification {classification!r}")
    comparisons = (
        ComparisonRun.objects.using(SHADOW_ALIAS)
        .filter(
            account__in=cohort.members.all(),
            period_start=cohort.eval_period_start,
            period_end=cohort.eval_period_end,
        )
        .order_by("-created_at")
    )
    source = next(
        (
            c
            for c in comparisons
            if any(d["fingerprint"] == fingerprint for d in c.report_json.get("diffs", []))
        ),
        None,
    )
    if source is None:
        raise MigrationError("diff_not_found", "no cohort evidence carries that fingerprint")
    return DiscrepancyDecision.objects.create(
        cohort=cohort,
        fingerprint=fingerprint,
        snapshot_hash=source.snapshot_hash,
        new_engine_version=source.new_engine_version,
        legacy_version_token=source.legacy_version_token,
        policy_identity=source.policy_identity,
        classification=classification,
        actor=actor,
        reason=reason,
    )
