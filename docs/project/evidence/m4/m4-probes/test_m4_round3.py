"""Round-three consumer, retry-budget and recovery validation probes."""

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from taryx.core.accounts import services as accounts
from taryx.core.accounts.seed import seed_demo_data
from taryx.core.market import services as market
from taryx.core.market.models import MarketOutbox, TransferWorkflow


@pytest.fixture
def workflow(db):
    return market.request_transfer(seed_demo_data()[0].supply_points.get(), timezone.now().date())


def completed_payload(workflow):
    return {
        "correlation_id": str(workflow.correlation_id),
        "seq": 1,
        "outcome": "completed",
        "occurred_at": timezone.now().isoformat(),
    }


def test_core_consumer_rejects_missing_schema_fields(workflow):
    with pytest.raises(ValueError):
        accounts.apply_transfer_outcome(
            workflow.supply_point, {"version": "1", "nmi": workflow.supply_point.nmi}
        )


def test_stale_outbox_delivery_does_not_reapply_old_correlation(workflow, monkeypatch):
    from django.db.models.query import QuerySet

    market.apply_callback(completed_payload(workflow))
    original = QuerySet.__iter__
    interleaved = False

    def competing_drain(queryset):
        nonlocal interleaved
        rows = original(queryset)
        if queryset.model is MarketOutbox and not interleaved:
            # Worker B materializes its pending event before worker A delivers it.
            rows = iter(list(rows))
            interleaved = True
            assert market.drain_market_outbox() == 1
            workflow.supply_point.refresh_from_db()
            market.request_transfer(workflow.supply_point, workflow.effective_date)
            assert workflow.supply_point.market_state == "pending"
        return rows

    monkeypatch.setattr(QuerySet, "__iter__", competing_drain)
    market.drain_market_outbox()
    workflow.supply_point.refresh_from_db()
    # Worker B must not replay a delivered correlation onto the new transfer.
    assert workflow.supply_point.market_state == "pending"


@override_settings(MARKET_MAX_ATTEMPTS=1)
def test_one_attempt_budget_allows_initial_submission(workflow):
    class Client:
        posts = 0

        def post(self, path, body):
            self.posts += 1
            return {"correlation_id": str(workflow.correlation_id), "status": "submitted", "seq": 0}

    client = Client()
    market.submit_workflow(workflow.correlation_id, client=client)
    assert client.posts == 1
    workflow.refresh_from_db()
    assert workflow.state == "submitted"


def test_boolean_recovery_sequence_cannot_abort_sweep(workflow):
    TransferWorkflow.objects.filter(pk=workflow.pk).update(attempts=1)

    class Client:
        def get(self, path):
            return {
                "correlation_id": str(workflow.correlation_id),
                "status": "completed",
                "last_seq": True,
            }

        def post(self, path, body):
            return {"correlation_id": str(workflow.correlation_id), "status": "submitted", "seq": 0}

    market.sweep(client=Client(), now=timezone.now() + timedelta(seconds=10))
    workflow.refresh_from_db()
    assert workflow.state != "completed"
