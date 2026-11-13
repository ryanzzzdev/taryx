from pathlib import Path
import importlib.util
from unittest.mock import patch
import pytest
from django.db import connections, OperationalError
from taryx.core.migration import services
from taryx.core.migration.legacy_adapter import LegacyFailure

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "helpers", ROOT / "docs/project/evidence/m3/m3_review_probes.py"
)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
m = h.m
legacy = h.legacy
pytestmark = pytest.mark.django_db(databases=["default", "shadow"], transaction=True)


def test_existing_failure_update_cannot_bypass_final_gate(legacy):
    c = m._cohort(None, refs=("ACC-001",))
    a, r = m._rated(None)
    with patch.object(services, "calculate", side_effect=LegacyFailure("unavailable", "probe")):
        services.run_comparison(r)
    row = services.run_comparison(r, base_url=legacy)
    actor = h.approve(c, row)
    original = services.evaluation_blockers
    calls = 0
    published = False

    def race(*args, **kwargs):
        nonlocal calls, published
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            with connections["shadow"].cursor() as cur:
                cur.execute("SET statement_timeout='2s'")
            try:
                with patch.object(
                    services, "calculate", side_effect=LegacyFailure("unavailable", "probe")
                ):
                    services.run_comparison(r)
                published = True
            except OperationalError as exc:
                if "statement timeout" not in str(exc):
                    raise
            finally:
                with connections["shadow"].cursor() as cur:
                    cur.execute("SET statement_timeout=0")
        return result

    with patch.object(services, "evaluation_blockers", side_effect=race):
        try:
            services.transition_cohort(c.id, "new_only", 3, actor, **m.GATE)
        except services.MigrationError:
            return
    assert not published, (
        "NEW_ONLY committed despite failed evidence publishing after final gate under account locks"
    )
