"""Independent contract probes; assertions describe required behaviour."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from taryx.core.accounts.seed import seed_demo_data
from taryx.core.market import services as s
from taryx.core.market.client import MarketHttpError, MarketTransport
from taryx.core.market.models import MarketOutbox, TransferWorkflow

pytestmark = pytest.mark.django_db


@pytest.fixture
def workflow():
    point = seed_demo_data()[0].supply_points.get()
    return s.request_transfer(point, timezone.now().date())


class Client:
    def post(self, *args):
        raise MarketHttpError(503, "unavailable")

    def get(self, *args):
        return {"status": "submitted", "last_seq": 0}


def callback(w):
    return {
        "correlation_id": str(w.correlation_id),
        "seq": 1,
        "outcome": "completed",
        "occurred_at": timezone.now().isoformat(),
    }


def test_http_failures_exhaust_to_terminal(workflow):
    for _ in range(5):
        s.submit_workflow(workflow.correlation_id, client=Client())
    s.sweep(client=Client(), now=timezone.now() + timedelta(minutes=1))
    workflow.refresh_from_db()
    assert workflow.state == "failed"


def test_uncertain_submit_polls_before_retry(workflow):
    class LostAck(Client):
        posts = 0
        gets = 0

        def post(self, *args):
            self.posts += 1
            raise MarketTransport("ack lost")

        def get(self, *args):
            self.gets += 1
            return {
                "correlation_id": str(workflow.correlation_id),
                "status": "completed",
                "last_seq": 1,
            }

    client = LostAck()
    s.submit_workflow(workflow.correlation_id, client=client)
    s.sweep(client=client, now=timezone.now() + timedelta(seconds=10))
    assert client.gets >= 1
    assert client.posts == 1


@pytest.mark.parametrize("field,value", [("seq", 1.5), ("occurred_at", None)])
def test_invalid_callback_cannot_complete(workflow, field, value):
    payload = callback(workflow)
    payload[field] = value
    with pytest.raises(ValueError):
        s.apply_callback(payload)


def test_terminal_callback_during_expiry_cannot_be_overwritten(workflow, monkeypatch):
    from django.db.models.query import QuerySet

    TransferWorkflow.objects.filter(pk=workflow.pk).update(
        state="submitted", deadline_at=timezone.now() - timedelta(seconds=1)
    )
    original = QuerySet.__iter__
    fired = False

    def interleaved(queryset):
        nonlocal fired
        rows = original(queryset)
        if (
            not fired
            and queryset.model is TransferWorkflow
            and "deadline_at" in str(queryset.query)
            and "submitted" in str(queryset.query)
        ):
            # Expiry read completed; callback commits before stale expiry save.
            rows = iter(list(rows))
            fired = True
            s.apply_callback(callback(workflow))
        return rows

    monkeypatch.setattr(QuerySet, "__iter__", interleaved)
    s.sweep(client=Client())
    assert fired
    workflow.refresh_from_db()
    assert workflow.state == "completed"


def test_outbox_validates_envelope(workflow):
    s.apply_callback(callback(workflow))
    MarketOutbox.objects.filter(workflow=workflow).update(topic="invalid", payload={})
    s.drain_market_outbox()
    workflow.supply_point.refresh_from_db()
    assert workflow.supply_point.market_state != "registered"


def test_ack_must_match_correlation(workflow):
    class WrongAck(Client):
        def post(self, *args):
            return {"correlation_id": str(uuid4()), "status": "submitted", "seq": 0}

    s.submit_workflow(workflow.correlation_id, client=WrongAck())
    workflow.refresh_from_db()
    assert workflow.state != "submitted"
