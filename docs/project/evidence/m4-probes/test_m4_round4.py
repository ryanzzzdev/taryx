"""The core consumer must validate against current database state, not a
supply-point instance read before a competing delivery."""

import pytest
from django.utils import timezone

from taryx.core.accounts import services as accounts
from taryx.core.accounts.models import SupplyPoint
from taryx.core.accounts.seed import seed_demo_data
from taryx.core.market import services as market


def test_consumer_rechecks_correlation_after_concurrent_delivery(db):
    """Model the race deterministically: hold an instance captured while
    the old transfer was still pending, let a competing drain register it
    and a newer transfer begin, then deliver the old outcome through the
    stale instance. It must raise and leave the newer pending transfer
    untouched — the check happens in the conditional UPDATE, not on the
    caller's stale object."""
    point = seed_demo_data()[0].supply_points.get()
    old = market.request_transfer(point, timezone.now().date())
    payload = {
        "version": "1",
        "correlation_id": str(old.correlation_id),
        "nmi": point.nmi,
        "effective_date": old.effective_date.isoformat(),
        "occurred_at": timezone.now().isoformat(),
    }
    market.apply_callback(
        {
            "correlation_id": str(old.correlation_id),
            "seq": 1,
            "outcome": "completed",
            "occurred_at": payload["occurred_at"],
        }
    )
    stale = SupplyPoint.objects.get(pk=point.pk)
    assert market.drain_market_outbox() == 1
    point.refresh_from_db()
    newer = market.request_transfer(point, old.effective_date)

    with pytest.raises(ValueError, match="pending transfer"):
        accounts.apply_transfer_outcome(stale, payload)
    point.refresh_from_db()
    assert point.pending_transfer_id == newer.correlation_id
    assert point.market_state == "pending"
