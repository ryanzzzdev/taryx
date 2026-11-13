from pathlib import Path
import importlib.util
from dataclasses import replace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import pytest
from django.db import close_old_connections
from django.core.management import call_command
from django.contrib.auth.models import User
from taryx.core.migration import services
from taryx.core.migration.models import ComparisonRun, DiscrepancyDecision
from taryx.core.migration.legacy_adapter import calculate, build_request
from taryx.core.metering.ingestion import ingest_nem12_content

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("migration_helpers", ROOT / "tests/test_migration.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
legacy = m.legacy
pytestmark = pytest.mark.django_db(databases=["default", "shadow"], transaction=True)


def approve(c, row, preserve=False):
    actor = User.objects.create_user("reviewer")
    for diff in row.report_json["diffs"]:
        services.decide_discrepancy(
            cohort=c,
            fingerprint=diff["fingerprint"],
            classification="preserve_client_policy"
            if preserve and diff["field"] in ("gst", "gst_total")
            else "approved_defect_correction",
            actor=actor,
            reason="review fixture",
        )
    return actor


def test_preserved_policy_survives_cutover(legacy):
    c = m._cohort(None, refs=("ACC-003",))
    a, r = m._rated(None, "acc3_heritage_day.nem12", "ACC-003")
    row = services.run_comparison(r, base_url=legacy)
    actor = approve(c, row, True)
    c = services.transition_cohort(c.id, "new_only", 3, actor, **m.GATE)
    op = m._process(m._admit(a, r, c).operation_id, legacy)
    assert op.invoice.gst == 0, "Preserve-client-policy approved, but NEW_ONLY charges heritage GST"


def test_successful_retry_clears_latest_failure(legacy):
    c = m._cohort(None, refs=("ACC-001",))
    a, r = m._rated(None)
    row = services.run_comparison(r, base_url=legacy)
    approve(c, row)
    m._set_fault(legacy, "unavailable")
    try:
        services.run_comparison(r, base_url=legacy)
    finally:
        m._set_fault(legacy, "ok")
    services.run_comparison(r, base_url=legacy)
    assert services.evaluation_blockers(c, **m.GATE) == []


def test_changed_legacy_engine_gets_new_comparison(legacy):
    a, r = m._rated(None)
    result = calculate(build_request(r.input_snapshot, r.input_digest), base_url=legacy)
    with patch.object(services, "calculate", return_value=result):
        first = services.run_comparison(r)
    with patch.object(services, "calculate", return_value=replace(result, engine_version="2.0.0")):
        second = services.run_comparison(r)
    assert first.pk != second.pk, (
        "Legacy engine upgrade reuses old comparison and approval identity"
    )


def test_cli_outbox_can_recover_legacy_operation(legacy, settings):
    settings.LEGACY_BASE_URL = legacy
    c = m._cohort(None, refs=("ACC-001",))
    a, r = m._rated(None)
    op = m._admit(a, r, c)
    call_command("drain_outbox")
    op.refresh_from_db()
    assert op.status == "complete"


def test_cutover_revalidates_concurrent_inputs(legacy):
    c = m._cohort(None, refs=("ACC-001",))
    a, r = m._rated(None)
    row = services.run_comparison(r, base_url=legacy)
    actor = approve(c, row)
    original = services.evaluation_blockers

    def race(*args, **kwargs):
        result = original(*args, **kwargs)

        def revise():
            close_old_connections()
            try:
                ingest_nem12_content((m.FIXTURES / "day1_rev1.nem12").read_bytes(), "race")
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(revise).result(timeout=10)
        return result

    with patch.object(services, "evaluation_blockers", side_effect=race):
        with pytest.raises(services.MigrationError):
            services.transition_cohort(c.id, "new_only", 3, actor, **m.GATE)


def test_correction_after_cutover_uses_new_amounts(legacy):
    c = m._cohort(None, refs=("ACC-001",))
    a, r = m._rated(None)
    first = m._process(m._admit(a, r, c).operation_id, legacy)
    row = services.run_comparison(r, base_url=legacy)
    actor = approve(c, row)
    c = services.transition_cohort(c.id, "new_only", 3, actor, **m.GATE)
    r = m.rate_account(a, m.DAY, m.NEXT, **m.GATE)
    second = m._process(m._admit(a, r, c, "new-engine").operation_id, legacy)
    assert second.adjustment is not None, (
        "Same input digest hides changed authoritative engine result"
    )
    assert second.adjustment.delta_total == r.total - first.invoice.total


@pytest.mark.parametrize(
    "payload",
    [[], {"protocol": "taryx-legacy/1", "lines": [], "net": "0", "gst": "0", "total": "0"}],
)
def test_malformed_json_response_is_inconclusive(legacy, payload):
    import json
    from unittest.mock import MagicMock

    a, r = m._rated(None)
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = json.dumps(payload).encode()
    with patch("urllib.request.urlopen", return_value=response):
        row = services.run_comparison(r, base_url=legacy)
    assert row.status == "inconclusive"
    assert row.failure_code == "malformed"
