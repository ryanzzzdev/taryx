"""Regression checks for correlation-scoped clearing and atomic supersession."""

import pytest
from django.utils import timezone

from taryx.core.accounts import services as accounts
from taryx.core.accounts.models import SupplyPoint
from taryx.core.accounts.seed import seed_demo_data
from taryx.core.market import services as market
from taryx.core.market.client import MarketHttpError


@pytest.mark.parametrize("ending", ["rejected", "failed"])
def test_superseded_terminal_cannot_clear_new_pending(db, ending):
    point = seed_demo_data()[0].supply_points.get()
    old = market.request_transfer(point, timezone.now().date())
    newer = market.request_transfer(point, old.effective_date)
    if ending == "rejected":
        market.apply_callback(
            {
                "correlation_id": str(old.correlation_id),
                "seq": 1,
                "outcome": "rejected",
                "occurred_at": timezone.now().isoformat(),
            }
        )
    else:

        class Conflict:
            def post(self, *args):
                raise MarketHttpError(409, "conflict")

        market.submit_workflow(old.correlation_id, client=Conflict())
    point.refresh_from_db()
    assert point.market_state == "pending"
    assert point.pending_transfer_id == newer.correlation_id


def test_current_clear_uses_database_state_and_replay_is_noop(db):
    point = seed_demo_data()[0].supply_points.get()
    stale = SupplyPoint.objects.get(pk=point.pk)
    workflow = market.request_transfer(point, timezone.now().date())
    accounts.clear_pending_transfer(stale, workflow.correlation_id)
    point.refresh_from_db()
    assert point.market_state == "none"
    assert point.pending_transfer_id is None
    accounts.begin_transfer(stale, workflow.correlation_id)
    payload = {
        "version": "1",
        "nmi": point.nmi,
        "correlation_id": str(workflow.correlation_id),
        "effective_date": workflow.effective_date.isoformat(),
        "occurred_at": timezone.now().isoformat(),
    }
    accounts.apply_transfer_outcome(stale, payload)
    accounts.apply_transfer_outcome(stale, payload)
    accounts.clear_pending_transfer(stale, workflow.correlation_id)
    point.refresh_from_db()
    assert point.market_state == "registered"
    assert point.pending_transfer_id == workflow.correlation_id
