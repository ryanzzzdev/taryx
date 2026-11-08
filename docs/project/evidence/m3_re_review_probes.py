"""Independent M3 re-review probes; run with pytest against local PostgreSQL.

These assert the required fail-closed behavior for a syntactically valid
legacy response that omits all output for a nonempty, billable snapshot.
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from taryx.core.migration import services
from taryx.core.migration.models import ComparisonRun

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("m3_test_helpers", ROOT / "tests/test_migration.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

pytestmark = pytest.mark.django_db(databases=["default", "shadow"], transaction=True)


def empty_response(run):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = json.dumps(
        {
            "protocol": "taryx-legacy/1",
            "engine": "legacy-sim",
            "engine_version": "1.0.0",
            "catalogue_version": "L-2003.4",
            "snapshot_hash": run.input_digest,
            "request_id": "missing-output-probe",
            "lines": [],
            "net": "0",
            "gst": "0",
            "total": "0",
        }
    ).encode()
    return response


def test_missing_legacy_outputs_are_inconclusive():
    cohort = m._cohort(None, refs=("ACC-001",))
    account, run = m._rated(None)
    assert run.total > 0 and run.lines.exists()
    with patch("urllib.request.urlopen", return_value=empty_response(run)):
        comparison = services.run_comparison(run)
    assert comparison.status == ComparisonRun.Status.INCONCLUSIVE, comparison.report_json
    assert any(
        b.startswith("inconclusive:") for b in services.evaluation_blockers(cohort, **m.GATE)
    )


def test_partial_legacy_outputs_cannot_issue_incomplete_invoice(legacy):
    cohort = m._cohort(None, refs=("ACC-001",))
    account, run = m._rated(None)
    op = m._admit(account, run, cohort, "missing-output-bill")
    from taryx.core.migration.legacy_adapter import build_request, calculate

    complete = calculate(build_request(run.input_snapshot, run.input_digest), base_url=legacy)
    payload = json.loads(empty_response(run).read.return_value)
    supply = [line for line in complete.lines if line.element == "supply"]
    assert supply and len(supply) < len(complete.lines)
    payload["lines"] = [
        {**vars(line), "segment": [str(line.segment_from), str(line.segment_to)]} for line in supply
    ]
    payload["net"] = sum(line.amount for line in supply)
    payload["gst"] = sum(line.gst for line in supply)
    payload["total"] = payload["net"] + payload["gst"]
    response = empty_response(run)
    response.read.return_value = json.dumps(payload, default=str).encode()
    with patch("urllib.request.urlopen", return_value=response):
        result = m._process(op.operation_id, "http://legacy.invalid")
    assert result.invoice_id is None, (
        f"issued {result.invoice.number} for {result.invoice.total}; "
        f"nonempty snapshot new-engine total is {run.total}"
    )


legacy = m.legacy


def test_invalid_line_identity_supersedes_prior_success(legacy):
    cohort = m._cohort(None, refs=("ACC-001",))
    account, run = m._rated(None)
    first = services.run_comparison(run, base_url=legacy)
    m._approve_all(cohort, first)
    assert services.evaluation_blockers(cohort, **m.GATE) == []
    calc = first.legacy_calculation
    payload = dict(calc.response_json)
    payload.update(
        {
            "protocol": "taryx-legacy/1",
            "engine": "legacy-sim",
            "engine_version": calc.engine_version,
            "catalogue_version": calc.catalogue_version,
            "snapshot_hash": run.input_digest,
            "request_id": "invalid-line-identity",
        }
    )
    for line in payload["lines"]:
        line["segment"] = [line.pop("segment_from"), line.pop("segment_to")]
    payload["lines"][0]["element"] = []
    response = empty_response(run)
    response.read.return_value = json.dumps(payload).encode()
    try:
        with patch("urllib.request.urlopen", return_value=response):
            latest = services.run_comparison(run)
    except Exception as exc:
        pytest.fail(
            f"malformed response escaped as {type(exc).__name__}: {exc}; "
            f"remaining blockers: {services.evaluation_blockers(cohort, **m.GATE)}"
        )
    assert latest.status == ComparisonRun.Status.INCONCLUSIVE
    assert any(
        b.startswith("inconclusive:") for b in services.evaluation_blockers(cohort, **m.GATE)
    )
