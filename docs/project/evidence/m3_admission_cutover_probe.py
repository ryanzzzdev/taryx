import importlib.util
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connections

from taryx.core.billing import services as billing
from taryx.core.migration import services
from taryx.core.migration.models import Cohort

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "review_helpers", ROOT / "docs/project/evidence/m3_review_probes.py"
)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
m = h.m
legacy = h.legacy

pytestmark = pytest.mark.django_db(databases=["default", "shadow"], transaction=True)


def test_old_route_cannot_issue_after_cutover(legacy):
    # Adapted to the remediated admission contract: routing is resolved
    # by admit_issue under the account lock via routing_resolver, so the
    # admission itself serializes with the cutover's member locks.
    cohort = m._cohort(None, refs=("ACC-001",))
    account, run = m._rated(None)
    comparison = services.run_comparison(run, base_url=legacy)
    actor = h.approve(cohort, comparison)

    reached_input_lock = Event()
    outcomes, errors, workers = [], [], []
    original_save = Cohort.save
    original_lock = billing.lock_inputs

    def bill():
        close_old_connections()
        try:
            op = billing.admit_issue(
                account,
                m.DAY,
                m.NEXT,
                run,
                "admission-race",
                routing_resolver=services.routing_for,
            )
            op = m._process(op.operation_id, legacy)
            outcomes.append(
                (
                    op.status,
                    op.invoice.calculation_source if op.invoice_id else None,
                )
            )
        except Exception as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    def observe_input_lock(*args, **kwargs):
        reached_input_lock.set()
        return original_lock(*args, **kwargs)

    def interleave_save(instance, *args, **kwargs):
        if instance.pk == cohort.pk and instance.routing_mode == "new_only" and not workers:
            worker = Thread(target=bill, daemon=True)
            workers.append(worker)
            worker.start()
            # Correct serialization may block admission until cutover commits.
            reached_input_lock.wait(2)
        return original_save(instance, *args, **kwargs)

    with (
        patch.object(Cohort, "save", interleave_save),
        patch.object(billing, "lock_inputs", observe_input_lock),
    ):
        try:
            services.transition_cohort(
                cohort.pk,
                "new_only",
                cohort.routing_revision,
                actor,
                **m.GATE,
            )
        finally:
            for worker in workers:
                worker.join(15)

    assert workers
    assert all(not worker.is_alive() for worker in workers)
    assert not errors, errors
    cohort.refresh_from_db()
    assert cohort.routing_mode == "new_only"
    assert ("complete", "legacy") not in outcomes, outcomes
