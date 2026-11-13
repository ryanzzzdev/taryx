"""Round-two boundary probes; expected assertions express decision 005."""

import io
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from taryx.core.accounts.seed import seed_demo_data
from taryx.core.market import services as s
from taryx.core.market.client import MarketClient, MarketMalformed
from taryx.core.market.models import MarketOutbox, TransferWorkflow


@pytest.fixture
def workflow(db):
    return s.request_transfer(seed_demo_data()[0].supply_points.get(), timezone.now().date())


class ProcessDied(BaseException):
    pass


class Coordinator:
    def __init__(self, workflow):
        self.correlation = str(workflow.correlation_id)
        self.posts = 0
        self.gets = 0

    def post(self, *args):
        self.posts += 1
        return {"correlation_id": self.correlation, "status": "submitted", "seq": 0}

    def get(self, *args):
        self.gets += 1
        return {"correlation_id": self.correlation, "status": "completed", "last_seq": 1}


def test_crash_after_remote_acceptance_requires_poll(workflow):
    client = Coordinator(workflow)

    def accepted_then_crashed(*args):
        client.posts += 1
        raise ProcessDied()

    with patch.object(client, "post", accepted_then_crashed), pytest.raises(ProcessDied):
        s.submit_workflow(workflow.correlation_id, client=client)
    # The transaction rolled back, but the coordinator accepted the request.
    s.sweep(client=client, now=timezone.now() + timedelta(seconds=10))
    assert client.gets == 1
    assert client.posts == 1


def test_recovered_terminal_at_budget_survives_crash(workflow):
    TransferWorkflow.objects.filter(pk=workflow.pk).update(attempts=4)
    client = Coordinator(workflow)
    with patch.object(s, "apply_callback", side_effect=ProcessDied), pytest.raises(ProcessDied):
        s.submit_workflow(workflow.correlation_id, client=client)
    s.sweep(client=client, now=timezone.now() + timedelta(seconds=10))
    workflow.refresh_from_db()
    assert workflow.state == "completed"


def test_reconcile_missing_correlation_cannot_complete(workflow):
    TransferWorkflow.objects.filter(pk=workflow.pk).update(
        state="reconciling", reconcile_deadline_at=timezone.now() + timedelta(minutes=1)
    )
    client = Coordinator(workflow)
    with patch.object(client, "get", return_value={"status": "completed", "last_seq": 1}):
        s.sweep(client=client)
    workflow.refresh_from_db()
    assert workflow.state == "reconciling"


@pytest.mark.parametrize("raw", [b"[]", b"null", b'"submitted"'])
def test_transport_rejects_nonobject_json(raw):
    with (
        patch("urllib.request.urlopen", return_value=io.BytesIO(raw)),
        pytest.raises(MarketMalformed),
    ):
        MarketClient("http://unused", "token").get("/transfers/unused")


@pytest.mark.parametrize(
    "field,value", [("effective_date", "wrong-date"), ("occurred_at", "not-a-timestamp")]
)
def test_outbox_rejects_invalid_contract_fields(workflow, field, value):
    s.apply_callback(
        {
            "correlation_id": str(workflow.correlation_id),
            "seq": 1,
            "outcome": "completed",
            "occurred_at": timezone.now().isoformat(),
        }
    )
    event = MarketOutbox.objects.get(workflow=workflow)
    event.payload[field] = value
    event.save(update_fields=["payload"])
    assert s.drain_market_outbox() == 0
    event.refresh_from_db()
    assert event.delivered_at is None
