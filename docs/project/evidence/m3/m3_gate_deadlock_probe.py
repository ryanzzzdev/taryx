from pathlib import Path
import importlib.util
from threading import Thread, Event
from unittest.mock import patch
import pytest
from django.db import connections, close_old_connections
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


def test_new_evidence_does_not_deadlock_cutover(legacy):
    c = m._cohort(None, refs=("ACC-001",))
    a, r = m._rated(None)
    row = services.run_comparison(r, base_url=legacy)
    actor = h.approve(c, row)
    acquired = Event()
    errors = []
    workers = []
    original = services._gate_lock

    def publish():
        close_old_connections()
        try:
            with connections["shadow"].cursor() as cur:
                cur.execute("SET statement_timeout='6s'")
            services.run_comparison(r, base_url=legacy)
        except Exception as exc:
            errors.append(("writer", type(exc).__name__, str(exc)))
        finally:
            connections.close_all()

    def hook(cohort_id, *, using):
        if using == "default":
            worker = Thread(target=publish)
            workers.append(worker)
            worker.start()
            assert acquired.wait(5), "Writer did not acquire advisory lock"
            original(cohort_id, using=using)
        else:
            original(cohort_id, using=using)
            acquired.set()

    with (
        patch.object(services, "_gate_lock", side_effect=hook),
        patch.object(
            services, "calculate", side_effect=LegacyFailure("unavailable", "new failure")
        ),
    ):
        try:
            services.transition_cohort(c.id, "new_only", 3, actor, **m.GATE)
        except services.MigrationError:
            pass
        except Exception as exc:
            errors.append(("cutover", type(exc).__name__, str(exc)))
        finally:
            for worker in workers:
                worker.join(10)
    assert not errors, errors
