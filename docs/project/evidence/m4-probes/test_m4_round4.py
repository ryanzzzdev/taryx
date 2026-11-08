"""Deterministic interleaving after the core consumer's supply-point read."""

from django.utils import timezone

from taryx.core.accounts import services as accounts
from taryx.core.accounts.seed import seed_demo_data
from taryx.core.market import services as market


def test_consumer_rechecks_correlation_after_concurrent_delivery(db, monkeypatch):
    point = seed_demo_data()[0].supply_points.get()
    old = market.request_transfer(point, timezone.now().date())
    market.apply_callback(
        {
            "correlation_id": str(old.correlation_id),
            "seq": 1,
            "outcome": "completed",
            "occurred_at": timezone.now().isoformat(),
        }
    )
    original = accounts.apply_transfer_outcome
    interleaved = False
    newer = None

    def competing_delivery(stale_point, payload):
        nonlocal interleaved, newer
        if not interleaved:
            interleaved = True
            # B has already read the old pending point. A delivers, then
            # a new transfer is admitted before B validates its stale object.
            assert market.drain_market_outbox() == 1
            point.refresh_from_db()
            newer = market.request_transfer(point, old.effective_date)
        return original(stale_point, payload)

    monkeypatch.setattr(accounts, "apply_transfer_outcome", competing_delivery)
    market.drain_market_outbox()
    point.refresh_from_db()
    assert point.pending_transfer_id == newer.correlation_id
    assert point.market_state == "pending"
