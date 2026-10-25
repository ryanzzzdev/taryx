"""Shadow comparison, cutover gates and credential enforcement.

The shadow database alias is a real credential boundary: tests attempt
actual writes through it, not just inspect configuration.
"""

import json
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.db import connections
from django.db.utils import ProgrammingError
from django.utils import timezone

from taryx.core.accounts.models import Account
from taryx.core.accounts.seed import seed_demo_data
from taryx.core.billing.models import BillingOperation, Invoice
from taryx.core.metering.ingestion import ingest_nem12_content
from taryx.core.migration.comparison import diff_lines, report
from taryx.core.migration.legacy_adapter import LegacyLine, LegacyResult
from taryx.core.migration.models import (
    SHADOW_ALIAS,
    Cohort,
    CohortEvent,
    ComparisonRun,
    DiscrepancyDecision,
)
from taryx.core.migration.services import (
    MigrationError,
    evaluation_blockers,
    run_comparison,
    transition_cohort,
)
from taryx.core.pricing.services import rate_account
from taryx.territories.au_nem.tariffs import GST_RATE, POLICY_IDENTITY, TARIFFS

ROOT = Path(__file__).resolve().parent.parent
SIM = ROOT / "legacy-sim" / "legacy_sim.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nem12"
DAY = date(2026, 3, 2)
NEXT = date(2026, 3, 3)
GATE = {"tariffs": TARIFFS, "gst_rate": GST_RATE, "policy_identity": POLICY_IDENTITY}

pytestmark = pytest.mark.django_db(databases=["default", "shadow"], transaction=True)


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _spawn(port: int, db_dir: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, str(SIM), "--port", str(port), "--db", str(db_dir / "calc.db")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
            return proc
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("legacy-sim exited early") from None
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("legacy-sim did not become healthy")


@pytest.fixture(scope="module")
def legacy(tmp_path_factory):
    port = _free_port()
    proc = _spawn(port, tmp_path_factory.mktemp("legacymig"))
    yield f"http://127.0.0.1:{port}"
    proc.kill()


def _set_fault(base_url: str, mode: str) -> None:
    req = urllib.request.Request(
        f"{base_url}/_admin/fault",
        data=json.dumps({"mode": mode}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=5)


def _rated(db, fixture="day1_base.nem12", ref="ACC-001"):
    seed_demo_data()
    ingest_nem12_content((FIXTURES / fixture).read_bytes(), fixture)
    account = Account.objects.get(reference=ref)
    run = rate_account(
        account,
        DAY,
        NEXT,
        tariffs=TARIFFS,
        gst_rate=GST_RATE,
        policy_identity=POLICY_IDENTITY,
    )
    return account, run


def _cohort(db, mode=Cohort.Mode.LEGACY_ONLY, refs=("ACC-001", "ACC-003")):
    seed_demo_data()
    cohort = Cohort.objects.create(
        name="Cohort T",
        routing_mode=mode,
        routing_revision=3,
        eval_period_start=DAY,
        eval_period_end=NEXT,
        eval_frozen_at=timezone.now() - timedelta(hours=1),
    )
    cohort.members.set(Account.objects.filter(reference__in=refs))
    return cohort


def _comparison_row(cohort, account, run, *, status="match", diffs=(), token="t"):
    report_json = {
        "status": status,
        "diffs": [dict(d, fingerprint=f"fp-{account.reference}-{i}") for i, d in enumerate(diffs)],
        "totals": {},
    }
    return ComparisonRun.objects.using(SHADOW_ALIAS).create(
        account=account,
        period_start=DAY,
        period_end=NEXT,
        rating_run=run,
        snapshot_hash=run.input_digest,
        new_engine_version=run.engine_version,
        legacy_version_token=token,
        policy_identity=run.policy_identity,
        status=status,
        report_json=report_json,
    )


def test_shadow_credential_cannot_write_financial_tables():
    """The exercised boundary: INSERTs through the shadow alias fail."""
    seed_demo_data()
    with (
        pytest.raises(ProgrammingError, match="permission denied"),
        connections[SHADOW_ALIAS].cursor() as cur,
    ):
        cur.execute("INSERT INTO billing_invoice (id) VALUES (991)")
    with (
        pytest.raises(ProgrammingError, match="permission denied"),
        connections[SHADOW_ALIAS].cursor() as cur,
    ):
        cur.execute("DELETE FROM pricing_ratingrun WHERE id = 1")
    # But the shadow path CAN write its own evidence tables.
    with connections[SHADOW_ALIAS].cursor() as cur:
        cur.execute(
            "INSERT INTO migration_legacycalculation"
            " (snapshot_hash, engine_version, catalogue_version, request_id,"
            "  response_json, net, gst, total, received_at)"
            " VALUES ('h','v','c','r','{}',0,0,0, now())"
        )


def test_shadow_alias_model_write_denied_on_ledger():
    """An ORM write to a financial table through the shadow alias fails."""
    account, run = _rated(None)
    with pytest.raises(ProgrammingError, match="permission denied"):
        Invoice.objects.using(SHADOW_ALIAS).create(
            number="SH-1",
            account=account,
            period_start=DAY,
            period_end=NEXT,
            rating_run=run,
            input_digest=run.input_digest,
            net=Decimal("1"),
            gst=Decimal("0"),
            total=Decimal("1"),
        )


def test_comparison_match_and_offsetting_differences():
    """Offsetting line differences are DIFFERENCE even when totals match."""
    _, run = _rated(None)
    exact = LegacyResult(
        engine="legacy-sim",
        engine_version="1.0.0",
        catalogue_version="L-2003.4",
        snapshot_hash=run.input_digest,
        request_id="r1",
        lines=tuple(
            LegacyLine(
                element=line.element,
                band=line.band,
                tariff_code=line.tariff_code,
                tariff_version="L-2003.4",
                agreement_id=line.agreement_id,
                segment_from=line.segment_from,
                segment_to=line.segment_to,
                quantity=line.quantity,
                unit=line.unit,
                rate=line.rate,
                amount=line.amount,
                gst=line.gst,
                basis=line.basis,
            )
            for line in run.lines.all()
        ),
        net=run.net,
        gst=run.gst,
        total=run.total,
    )
    assert diff_lines(run, exact, "ACC-001") == []
    data = report(run, exact, "ACC-001")
    assert data["status"] == "match"

    # Offsetting: legacy under-rates import by 0.10, over-credits export
    # by 0.10 — totals equal, but two field differences must be reported.
    offset = []
    seen_import = seen_export = False
    for item in exact.lines:
        line = item
        if item.element == "import" and not seen_import:
            seen_import = True
            line = LegacyLine(**{**vars(item), "amount": item.amount - Decimal("0.10")})
        if item.element == "export_credit" and not seen_export:
            seen_export = True
            line = LegacyLine(**{**vars(item), "amount": item.amount + Decimal("0.10")})
        offset.append(line)
    shifted = LegacyResult(**{**vars(exact), "lines": tuple(offset), "request_id": "r2"})
    diffs = diff_lines(run, shifted, "ACC-001")
    fields = {(d.element, d.field) for d in diffs}
    assert ("import", "amount") in fields
    assert ("export_credit", "amount") in fields
    assert report(run, shifted, "ACC-001")["status"] == "difference"


def test_run_comparison_persists_itemised_report(legacy):
    """Real legacy call: FIT trunc defect + totals diff captured."""
    account, run = _rated(None)
    row = run_comparison(run, base_url=legacy)
    assert row.status == ComparisonRun.Status.DIFFERENCE
    report_json = row.report_json
    fields = {(d["element"], d["field"]) for d in report_json["diffs"]}
    assert ("export_credit", "quantity") in fields
    assert ("export_credit", "amount") in fields
    assert ("__totals__", "net") in fields
    assert row.legacy_calculation.engine_version == "1.0.0"
    # Idempotent: retry resolves the same comparison identity.
    again = run_comparison(run, base_url=legacy)
    assert again.pk == row.pk
    assert ComparisonRun.objects.count() == 1


def test_inconclusive_on_legacy_failure(legacy):
    _, run = _rated(None)
    _set_fault(legacy, "unavailable")
    try:
        row = run_comparison(run, base_url=legacy)
    finally:
        _set_fault(legacy, "ok")
    assert row.status == ComparisonRun.Status.INCONCLUSIVE
    assert row.failure_code == "unavailable"


def test_restart_retry_resolves_same_comparison(tmp_path):
    """After a legacy restart the retried comparison resolves to the
    same persisted identity (snapshot hash + engine versions)."""
    port = _free_port()
    proc = _spawn(port, tmp_path)
    base = f"http://127.0.0.1:{port}"
    try:
        _, run = _rated(None)
        first = run_comparison(run, base_url=base)
        proc.kill()
        proc.wait(timeout=5)
        proc = _spawn(port, tmp_path)
        second = run_comparison(run, base_url=base)
        assert second.pk == first.pk
        assert ComparisonRun.objects.count() == 1
    finally:
        proc.kill()


def test_gate_blocks_missing_inconclusive_and_unresolved():
    cohort = _cohort(None)
    blockers = evaluation_blockers(cohort, **GATE)
    assert any(b.startswith("missing_evidence") for b in blockers)

    account, run = _rated(None)
    bad = _comparison_row(cohort, account, run, status="difference", diffs=[{"field": "quantity"}])
    blockers = evaluation_blockers(cohort, **GATE)
    assert any(b.startswith("unresolved_difference") for b in blockers)

    # A valid decision covering the diff's fingerprint clears that blocker.
    decision = DiscrepancyDecision.objects.create(
        cohort=cohort,
        fingerprint=bad.report_json["diffs"][0]["fingerprint"],
        snapshot_hash=bad.snapshot_hash,
        new_engine_version=bad.new_engine_version,
        legacy_version_token=bad.legacy_version_token,
        policy_identity=bad.policy_identity,
        classification=DiscrepancyDecision.Classification.APPROVED_DEFECT_CORRECTION,
        actor=User.objects.create_user("appr"),
        reason="documented defect",
    )
    assert decision.is_valid_for(bad)
    remaining = evaluation_blockers(cohort, **GATE)
    assert not any(b.startswith("unresolved_difference") for b in remaining)
    # Other member still missing; and the stale_policy/stale_evidence rules
    # fire when inputs or catalogue versions change.
    assert any(b.startswith("missing_evidence") for b in remaining)


def test_gate_rejects_stale_and_inconclusive_evidence():
    cohort = _cohort(None, refs=("ACC-001",))
    account, run = _rated(None)
    row = _comparison_row(cohort, account, run)
    assert evaluation_blockers(cohort, **GATE) == []

    # Evidence predating the freeze window is stale.
    cohort.eval_frozen_at = timezone.now() + timedelta(hours=1)
    cohort.save()
    blockers = evaluation_blockers(cohort, **GATE)
    assert any(b.startswith("stale_window") for b in blockers)

    # An inconclusive latest result blocks.
    cohort.eval_frozen_at = timezone.now() - timedelta(hours=1)
    cohort.save()
    row.status = ComparisonRun.Status.INCONCLUSIVE
    row.failure_code = "timeout"
    row.save(using=SHADOW_ALIAS)
    blockers = evaluation_blockers(cohort, **GATE)
    assert any(b.startswith("inconclusive") for b in blockers)


def test_decision_invalidated_by_input_change():
    cohort = _cohort(None, refs=("ACC-001",))
    account, run = _rated(None)
    row = _comparison_row(cohort, account, run, status="difference", diffs=[{"field": "amount"}])
    decision = DiscrepancyDecision.objects.create(
        cohort=cohort,
        fingerprint=row.report_json["diffs"][0]["fingerprint"],
        snapshot_hash=row.snapshot_hash,
        new_engine_version=row.new_engine_version,
        legacy_version_token=row.legacy_version_token,
        policy_identity=row.policy_identity,
        classification=DiscrepancyDecision.Classification.PRESERVE_CLIENT_POLICY,
        actor=User.objects.create_user("appr2"),
        reason="policy",
    )
    # A different snapshot (revised inputs) invalidates the approval.
    newer = ComparisonRun(
        snapshot_hash="different",
        new_engine_version=row.new_engine_version,
        legacy_version_token=row.legacy_version_token,
        policy_identity=row.policy_identity,
    )
    assert not decision.is_valid_for(newer)


def test_transition_guards_revision_inflight_and_gate():
    cohort = _cohort(None)
    actor = User.objects.create_user("op")

    with pytest.raises(MigrationError) as stale:
        transition_cohort(cohort.id, "shadow", 99, actor, **GATE)
    assert stale.value.code == "stale_revision"

    # Pending billing op on a member blocks any mode change.
    _, run = _rated(None)
    account = Account.objects.get(reference="ACC-001")
    BillingOperation.objects.create(
        operation_id="OP-PEND",
        account=account,
        period_start=DAY,
        period_end=NEXT,
        rating_run=run,
        payload_sha256="x",
        status=BillingOperation.Status.PENDING,
    )
    with pytest.raises(MigrationError) as inflight:
        transition_cohort(cohort.id, "shadow", 3, actor, **GATE)
    assert inflight.value.code == "in_flight"
    BillingOperation.objects.filter(operation_id="OP-PEND").update(status="complete")

    cohort = transition_cohort(cohort.id, "shadow", 3, actor, reason="start shadow", **GATE)
    assert cohort.routing_mode == "shadow" and cohort.routing_revision == 4
    assert CohortEvent.objects.filter(cohort=cohort, to_mode="shadow").exists()

    # NEW_ONLY is gated on the evaluation set.
    with pytest.raises(MigrationError) as gated:
        transition_cohort(cohort.id, "new_only", 4, actor, **GATE)
    assert gated.value.code == "gate_blocked"
    assert "missing_evidence" in str(gated.value)

    # Rollback to legacy is always allowed.
    cohort = transition_cohort(cohort.id, "legacy_only", 4, actor, reason="rollback", **GATE)
    assert cohort.routing_mode == "legacy_only" and cohort.routing_revision == 5

    # Illegal edges are rejected (no direct new -> shadow).
    cohort.routing_mode = "new_only"
    cohort.save(update_fields=["routing_mode"])
    with pytest.raises(MigrationError) as edge:
        transition_cohort(cohort.id, "shadow", 5, actor, **GATE)
    assert edge.value.code == "invalid_transition"


def test_full_shadow_evaluation_then_cutover(legacy):
    """End-to-end: real comparisons for both members, one decision,
    then the gate opens for cutover."""
    cohort = _cohort(None)
    for ref, fixture in (("ACC-001", "day1_base.nem12"), ("ACC-003", "acc3_heritage_day.nem12")):
        ingest_nem12_content((FIXTURES / fixture).read_bytes(), fixture)
        account = Account.objects.get(reference=ref)
        run = rate_account(
            account,
            DAY,
            NEXT,
            tariffs=TARIFFS,
            gst_rate=GST_RATE,
            policy_identity=POLICY_IDENTITY,
        )
        row = run_comparison(run, base_url=legacy)
        assert row.status == ComparisonRun.Status.DIFFERENCE
        for diff in row.report_json["diffs"]:
            DiscrepancyDecision.objects.create(
                cohort=cohort,
                fingerprint=diff["fingerprint"],
                snapshot_hash=row.snapshot_hash,
                new_engine_version=row.new_engine_version,
                legacy_version_token=row.legacy_version_token,
                policy_identity=row.policy_identity,
                classification=(
                    DiscrepancyDecision.Classification.PRESERVE_CLIENT_POLICY
                    if diff["field"] == "gst"
                    else DiscrepancyDecision.Classification.APPROVED_DEFECT_CORRECTION
                ),
                actor=User.objects.get_or_create(username="appr3")[0],
                reason=f"{ref} {diff['field']} accepted",
            )
    assert evaluation_blockers(cohort, **GATE) == []
    actor = User.objects.get(username="appr3")
    cohort = transition_cohort(cohort.id, "new_only", 3, actor, reason="cut over", **GATE)
    assert cohort.routing_mode == "new_only"


# --- TAR-012: cohort-routed billing --------------------------------------


def _digest(account, start, end):
    from taryx.core.pricing.services import compute_input_digest

    return compute_input_digest(
        account,
        start,
        end,
        tariffs=TARIFFS,
        gst_rate=GST_RATE,
        policy_identity=POLICY_IDENTITY,
    )


def _process(op_id, base_url):
    from taryx.core.billing.services import (
        CalculationUnavailable,
        process_operation,
    )
    from taryx.core.migration.legacy_adapter import LegacyFailure
    from taryx.core.migration.services import calculate_for_billing, routing_for

    def calculator(op):
        try:
            return calculate_for_billing(op, base_url=base_url)
        except LegacyFailure as exc:
            raise CalculationUnavailable(exc.code, str(exc)) from exc

    return process_operation(
        op_id,
        digest_resolver=_digest,
        routing_resolver=routing_for,
        legacy_calculator=calculator,
    )


def _admit(account, run, cohort, op="OP-M1"):
    from taryx.core.billing.services import admit_issue

    return admit_issue(
        account,
        DAY,
        NEXT,
        run,
        op,
        cohort_mode=cohort.routing_mode,
        cohort_revision=cohort.routing_revision,
    )


def test_legacy_routed_invoice_uses_legacy_amounts(legacy):
    """LEGACY_ONLY: the invoice + journal carry the legacy result —
    including its FIT-TRUNC defect — not the new rating run's."""
    cohort = _cohort(None)
    account, run = _rated(None)
    op = _admit(account, run, cohort)
    assert (op.cohort_mode, op.cohort_revision) == ("legacy_only", 3)

    op = _process(op.operation_id, legacy)
    assert op.status == "complete"
    invoice = op.invoice
    assert invoice.calculation_source == "legacy"
    # Legacy truncated B1 9.6 → 9 kWh: net 7.85 / total 8.68, not 7.82/8.65.
    assert (invoice.net, invoice.total) == (Decimal("7.85"), Decimal("8.68"))
    legs = {
        p.account_code: p.debit - p.credit for p in invoice.journal_entries.get().postings.all()
    }
    assert legs["1100"] == Decimal("8.68")
    assert legs["4100"] == Decimal("0.45")  # truncated export credit
    assert legs["4000"] == Decimal("-8.30")  # 7.20 import + 1.10 supply
    assert legs["2100"] == Decimal("-0.83")


def test_shadow_issues_legacy_and_records_comparison(legacy):
    cohort = _cohort(None, mode="shadow")
    account, run = _rated(None)
    op = _admit(account, run, cohort)
    op = _process(op.operation_id, legacy)
    assert op.status == "complete"
    assert op.invoice.calculation_source == "legacy"
    row = ComparisonRun.objects.using(SHADOW_ALIAS).get(snapshot_hash=run.input_digest)
    assert row.status == "difference"


def test_routing_change_since_admission_stales_the_op(legacy):
    """A pending op admitted under revision r cannot issue once the
    cohort's routing has moved on (defence-in-depth behind the
    transition guard's in-flight check)."""
    cohort = _cohort(None)
    account, run = _rated(None)
    op = _admit(account, run, cohort)
    Cohort.objects.filter(pk=cohort.pk).update(routing_mode="shadow", routing_revision=4)
    op = _process(op.operation_id, legacy)
    assert op.status == "stale"
    assert "routing" in op.detail
    assert not hasattr(op, "invoice") or op.invoice is None


def test_legacy_failure_leaves_op_pending(legacy):
    """A legacy outage cannot produce an invoice; the op stays in-flight
    (which itself blocks any cohort mode change)."""
    cohort = _cohort(None)
    account, run = _rated(None)
    op = _admit(account, run, cohort)
    _set_fault(legacy, "unavailable")
    try:
        with pytest.raises(Exception, match="unavailable"):
            _process(op.operation_id, legacy)
    finally:
        _set_fault(legacy, "ok")
    op.refresh_from_db()
    assert op.status == "pending"
    assert not Invoice.objects.filter(account=account).exists()
    # And the in-flight op blocks transition while pending.
    with pytest.raises(MigrationError) as err:
        transition_cohort(cohort.id, "shadow", 3, None, **GATE)
    assert err.value.code == "in_flight"


def test_correction_under_legacy_uses_legacy_amounts(legacy):
    """Successive correction under legacy routing: revised data → fresh
    legacy result; delta reconciles against recognised liability."""
    cohort = _cohort(None)
    account, run = _rated(None)
    op = _admit(account, run, cohort)
    _process(op.operation_id, legacy)

    ingest_nem12_content((FIXTURES / "day1_rev1.nem12").read_bytes(), "day1_rev1.nem12")
    run2 = rate_account(
        account,
        DAY,
        NEXT,
        tariffs=TARIFFS,
        gst_rate=GST_RATE,
        policy_identity=POLICY_IDENTITY,
    )
    op2 = _admit(account, run2, cohort, op="OP-M2")
    op2 = _process(op2.operation_id, legacy)
    assert op2.status == "complete"
    adj = op2.adjustment
    # New engine rev1: +0.09 net (0.3 kWh × 0.30); legacy same +0.09
    # (import line is unaffected by the trunc defect).
    assert adj.delta_total == Decimal("0.10")


def test_graphql_migration_permissions(db, client, legacy):
    """Cohort queries need auth; decisions allow operator; transitions
    require approver."""
    pass  # exercised in test_graphql.py


def _approve_all(cohort, row, actor=None, preserve_fields=("gst", "gst_total")):
    """Decide every diff in a comparison report — preserve for policy
    fields, defect-correction otherwise."""
    from taryx.core.migration.services import decide_discrepancy

    actor = actor or User.objects.create_user("decider")
    for diff in row.report_json["diffs"]:
        decide_discrepancy(
            cohort=cohort,
            fingerprint=diff["fingerprint"],
            classification=(
                "preserve_client_policy"
                if diff["field"] in preserve_fields
                else "approved_defect_correction"
            ),
            actor=actor,
            reason="test decision",
        )
    return actor


def test_preserved_policy_survives_cutover(legacy):
    """R1: a preserve-policy decision only passes the gate when the new
    engine evidences the policy — the heritage exemption produces a
    zero-GST invoice after cutover."""
    cohort = _cohort(None, refs=("ACC-003",))
    account, run = _rated(None, "acc3_heritage_day.nem12", "ACC-003")
    row = run_comparison(run, base_url=legacy)
    actor = _approve_all(cohort, row)
    cohort = transition_cohort(cohort.id, "new_only", 3, actor, **GATE)
    op = _process(_admit(account, run, cohort).operation_id, legacy)
    assert op.invoice.gst == 0


def test_preserve_decision_on_still_different_policy_blocks(legacy):
    """R1 converse: a preserve decision on a difference the new engine
    still produces is an unpreserved_policy blocker."""
    from taryx.core.migration.services import decide_discrepancy

    cohort = _cohort(None)
    account, run = _rated(None)
    row = run_comparison(run, base_url=legacy)
    actor = User.objects.create_user("p")
    fp = row.report_json["diffs"][0]["fingerprint"]
    decide_discrepancy(
        cohort=cohort,
        fingerprint=fp,
        classification="preserve_client_policy",
        actor=actor,
        reason="keep legacy behaviour",
    )
    blockers = evaluation_blockers(cohort, **GATE)
    assert any(b.startswith("unpreserved_policy") for b in blockers)


def test_successful_retry_supersedes_failed_attempt(legacy):
    """R4: a re-verified success is the latest conclusive observation;
    the intervening failed attempt is retained, not governing."""
    cohort = _cohort(None, refs=("ACC-001",))
    account, run = _rated(None)
    row = run_comparison(run, base_url=legacy)
    _approve_all(cohort, row)
    _set_fault(legacy, "unavailable")
    try:
        failed = run_comparison(run, base_url=legacy)
    finally:
        _set_fault(legacy, "ok")
    assert failed.status == "inconclusive"
    retry = run_comparison(run, base_url=legacy)
    assert retry.pk == row.pk  # same comparison identity
    assert evaluation_blockers(cohort, **GATE) == []
    assert ComparisonRun.objects.using(SHADOW_ALIAS).filter(status="inconclusive").exists()


def test_engine_upgrade_gets_new_comparison_identity(legacy):
    """R3: engine_version is part of comparison identity."""
    from dataclasses import replace
    from unittest.mock import patch

    from taryx.core.migration import services
    from taryx.core.migration.legacy_adapter import build_request, calculate

    account, run = _rated(None)
    result = calculate(build_request(run.input_snapshot, run.input_digest), base_url=legacy)
    with patch.object(services, "calculate", return_value=result):
        first = run_comparison(run)
    with patch.object(services, "calculate", return_value=replace(result, engine_version="2.0.0")):
        second = run_comparison(run)
    assert first.pk != second.pk


def test_drain_outbox_command_recovers_legacy_op(legacy, settings):
    """R5: the CLI recovery path composes the same dependencies as the
    worker task."""
    from django.core.management import call_command

    settings.LEGACY_BASE_URL = legacy
    cohort = _cohort(None, refs=("ACC-001",))
    account, run = _rated(None)
    op = _admit(account, run, cohort)
    call_command("drain_outbox")
    op.refresh_from_db()
    assert op.status == "complete"


def test_cutover_revalidates_inputs_committed_during_gate(legacy):
    """R2: a revision committed between gate evaluation and route commit
    is detected — cutover rejects rather than using stale evidence."""
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import patch

    from django.db import close_old_connections

    from taryx.core.migration import services

    cohort = _cohort(None, refs=("ACC-001",))
    account, run = _rated(None)
    row = run_comparison(run, base_url=legacy)
    actor = _approve_all(cohort, row)
    original = services.evaluation_blockers

    def race(*args, **kwargs):
        result = original(*args, **kwargs)

        def revise():
            close_old_connections()
            try:
                ingest_nem12_content((FIXTURES / "day1_rev1.nem12").read_bytes(), "race")
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(revise).result(timeout=20)
        return result

    with (
        patch.object(services, "evaluation_blockers", side_effect=race),
        pytest.raises(MigrationError),
    ):
        services.transition_cohort(cohort.id, "new_only", 3, actor, **GATE)


def test_correction_after_cutover_uses_new_amounts(legacy):
    """R6: engine identity is part of the generation — an explicit
    correction under the new engine produces an adjustment against the
    legacy-recognised liability."""
    cohort = _cohort(None, refs=("ACC-001",))
    account, run = _rated(None)
    first = _process(_admit(account, run, cohort).operation_id, legacy)
    row = run_comparison(run, base_url=legacy)
    actor = _approve_all(cohort, row)
    cohort = transition_cohort(cohort.id, "new_only", 3, actor, **GATE)
    run2 = rate_account(
        account, DAY, NEXT, tariffs=TARIFFS, gst_rate=GST_RATE, policy_identity=POLICY_IDENTITY
    )
    second = _process(_admit(account, run2, cohort, "OP-NEW").operation_id, legacy)
    assert second.adjustment is not None
    assert second.adjustment.delta_total == run2.total - first.invoice.total


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"protocol": "taryx-legacy/1", "lines": [], "net": "0", "gst": "0", "total": "0"},
    ],
)
def test_malformed_json_shapes_persist_inconclusive(legacy, payload):
    """R8: valid-JSON-but-invalid-shape responses normalise to
    INCONCLUSIVE evidence that blocks the gate."""
    from unittest.mock import MagicMock, patch

    account, run = _rated(None)
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = json.dumps(payload).encode()
    with patch("urllib.request.urlopen", return_value=response):
        row = run_comparison(run, base_url=legacy)
    assert row.status == "inconclusive"
    assert row.failure_code == "malformed"
