"""Round-two boundaries: supply completeness, malformed IDs, shadow failures."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from taryx.core.billing.models import BillingOperation
from taryx.core.migration import services
from taryx.core.migration.legacy_adapter import build_request, calculate

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "m3_r1_helpers", ROOT / "docs/project/evidence/m3_re_review_probes.py"
)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
m = h.m
legacy = m.legacy
pytestmark = pytest.mark.django_db(databases=["default", "shadow"], transaction=True)


def response_with_lines(run, result, lines):
    payload = json.loads(h.empty_response(run).read.return_value)
    payload.update(engine_version=result.engine_version, catalogue_version=result.catalogue_version)
    payload["lines"] = [
        {**vars(line), "segment": [str(line.segment_from), str(line.segment_to)]} for line in lines
    ]
    payload["net"] = sum(line.amount for line in lines)
    payload["gst"] = sum(line.gst for line in lines)
    payload["total"] = payload["net"] + payload["gst"]
    response = h.empty_response(run)
    response.read.return_value = json.dumps(payload, default=str).encode()
    return response


def test_omitted_daily_supply_cannot_issue(legacy):
    cohort = m._cohort(None, refs=("ACC-001",))
    account, run = m._rated(None)
    complete = calculate(build_request(run.input_snapshot, run.input_digest), base_url=legacy)
    lines = [line for line in complete.lines if line.element != "supply"]
    assert len(lines) < len(complete.lines)
    op = m._admit(account, run, cohort, "missing-supply")
    with patch("urllib.request.urlopen", return_value=response_with_lines(run, complete, lines)):
        result = m._process(op.operation_id, "http://legacy.invalid")
    assert result.invoice_id is None, (
        f"omitted daily supply but issued {result.invoice.total}; "
        f"complete legacy total {complete.total}"
    )
    assert result.status == BillingOperation.Status.FAILED


def test_out_of_range_agreement_id_is_inconclusive(legacy):
    cohort = m._cohort(None, refs=("ACC-001",))
    account, run = m._rated(None)
    first = services.run_comparison(run, base_url=legacy)
    m._approve_all(cohort, first)
    complete = calculate(build_request(run.input_snapshot, run.input_digest), base_url=legacy)
    response = response_with_lines(run, complete, complete.lines)
    payload = json.loads(response.read.return_value)
    payload["lines"][0]["agreement_id"] = "EXPONENT_PLACEHOLDER"
    # A valid JSON numeric token that the decoder materialises as infinity.
    response.read.return_value = (
        json.dumps(payload).replace('"EXPONENT_PLACEHOLDER"', "1e309").encode()
    )
    try:
        with patch("urllib.request.urlopen", return_value=response):
            latest = services.run_comparison(run)
    except Exception as exc:
        pytest.fail(
            f"escaped {type(exc).__name__}: {exc}; "
            f"gate blockers: {services.evaluation_blockers(cohort, **m.GATE)}"
        )
    assert latest.status == "inconclusive"
    assert any(
        b.startswith("inconclusive:") for b in services.evaluation_blockers(cohort, **m.GATE)
    )


def test_malformed_shadow_billing_blocks_cutover_after_failed_operation(legacy):
    cohort = m._cohort(None, mode="shadow", refs=("ACC-001",))
    account, run = m._rated(None)
    first = services.run_comparison(run, base_url=legacy)
    actor = m._approve_all(cohort, first)
    op = m._admit(account, run, cohort, "shadow-malformed")
    with patch("urllib.request.urlopen", return_value=h.empty_response(run)):
        failed = m._process(op.operation_id, "http://legacy.invalid")
    assert failed.status == BillingOperation.Status.FAILED
    assert failed.outbox_event.delivered_at is not None
    with pytest.raises(services.MigrationError, match="inconclusive"):
        services.transition_cohort(cohort.pk, "new_only", cohort.routing_revision, actor, **m.GATE)


@pytest.mark.parametrize("code", ["timeout", "unavailable"])
def test_transient_legacy_failure_stays_recoverable(code):
    from taryx.core.billing.services import CalculationUnavailable, process_operation

    cohort = m._cohort(None, refs=("ACC-001",))
    account, run = m._rated(None)
    op = m._admit(account, run, cohort, "transient")
    with pytest.raises(CalculationUnavailable):
        process_operation(
            op.operation_id,
            digest_resolver=m._digest,
            routing_resolver=services.routing_for,
            legacy_calculator=lambda op: (_ for _ in ()).throw(CalculationUnavailable(code, code)),
        )
    op.refresh_from_db()
    assert op.status == BillingOperation.Status.PENDING
    assert op.outbox_event.delivered_at is None
