from pathlib import Path
import importlib.util
from unittest.mock import patch, MagicMock
import json
import pytest
from taryx.core.migration import services

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "review_helpers", ROOT / "docs/project/evidence/m3/m3_review_probes.py"
)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
m = h.m
legacy = h.legacy
pytestmark = pytest.mark.django_db(databases=["default", "shadow"], transaction=True)


def test_latest_failure_blocks_even_after_previous_success(legacy):
    c = m._cohort(None, refs=("ACC-001",))
    a, r = m._rated(None)
    row = services.run_comparison(r, base_url=legacy)
    h.approve(c, row)
    m._set_fault(legacy, "unavailable")
    try:
        services.run_comparison(r, base_url=legacy)
    finally:
        m._set_fault(legacy, "ok")
    assert any(x.startswith("inconclusive:") for x in services.evaluation_blockers(c, **m.GATE))


def test_cutover_then_rollback_can_correct_same_inputs(legacy):
    c = m._cohort(None, refs=("ACC-001",))
    a, r = m._rated(None)
    first = m._process(m._admit(a, r, c, "first").operation_id, legacy)
    row = services.run_comparison(r, base_url=legacy)
    actor = h.approve(c, row)
    c = services.transition_cohort(c.id, "new_only", 3, actor, **m.GATE)
    r = m.rate_account(a, m.DAY, m.NEXT, **m.GATE)
    second = m._process(m._admit(a, r, c, "second").operation_id, legacy)
    assert second.adjustment is not None
    c = services.transition_cohort(c.id, "legacy_only", c.routing_revision, actor, **m.GATE)
    r = m.rate_account(a, m.DAY, m.NEXT, **m.GATE)
    third = m._process(m._admit(a, r, c, "third").operation_id, legacy)
    assert third.status == "complete"
    assert third.adjustment.delta_total == -second.adjustment.delta_total


@pytest.mark.parametrize("bad", ["nonfinite", "null_version"])
def test_invalid_response_is_inconclusive(legacy, bad):
    a, r = m._rated(None)
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    payload = {
        "protocol": "taryx-legacy/1",
        "lines": [],
        "net": "0",
        "gst": "0",
        "total": "0",
        "engine": "legacy-sim",
        "engine_version": "1.0.0",
        "catalogue_version": "L-2003.4",
        "snapshot_hash": r.input_digest,
        "request_id": "review",
    }
    if bad == "nonfinite":
        payload["net"] = "sNaN"
    else:
        payload["engine_version"] = None
    response.read.return_value = json.dumps(payload).encode()
    with patch("urllib.request.urlopen", return_value=response):
        row = services.run_comparison(r, base_url=legacy)
    assert row.status == "inconclusive"


def test_new_unapproved_evidence_during_cutover_is_rechecked(legacy):
    # Updated for the shared gate-lock protocol: the write either commits
    # before the final gate re-read (then full re-evaluation rejects the
    # cutover) or blocks on the advisory lock — it can never land between
    # the final read and the route commit.
    from dataclasses import replace
    from django.db import connections, OperationalError
    from taryx.core.migration.legacy_adapter import calculate, build_request

    c = m._cohort(None, refs=("ACC-001",))
    a, r = m._rated(None)
    row = services.run_comparison(r, base_url=legacy)
    actor = h.approve(c, row)
    result = calculate(build_request(r.input_snapshot, r.input_digest), base_url=legacy)
    original = services.evaluation_blockers
    published = False

    def race(*args, **kwargs):
        nonlocal published
        blockers = original(*args, **kwargs)
        with connections["shadow"].cursor() as cur:
            cur.execute("SET statement_timeout='2s'")
        try:
            with patch.object(
                services, "calculate", return_value=replace(result, engine_version="2.0.0")
            ):
                services.run_comparison(r)
            published = True
        except OperationalError as exc:
            if "statement timeout" not in str(exc):
                raise
        finally:
            with connections["shadow"].cursor() as cur:
                cur.execute("SET statement_timeout=0")
        return blockers

    with patch.object(services, "evaluation_blockers", side_effect=race):
        try:
            services.transition_cohort(c.id, "new_only", 3, actor, **m.GATE)
        except services.MigrationError:
            return
    assert not published, "NEW_ONLY committed despite evidence publishing after the final gate read"
