"""Account-side services — the validating core consumer for bounded
integration outcomes. The market adapter's drain never writes core
state itself; it hands the verified envelope here. Every mutation is a
single conditional UPDATE so validation and write are atomic against
current database state — a caller holding a stale instance can never
overwrite a state that moved on since it was read."""

from datetime import date, datetime
from uuid import UUID

from taryx.core.accounts.models import SupplyPoint


def begin_transfer(supply_point: SupplyPoint, transfer_id) -> None:
    """Mark the supply point as having `transfer_id` in flight. A newer
    request supersedes an older pending mark — the old transfer's
    outcome can then only fail its correlation check and surface as a
    visible undelivered error, never corrupt the newer state."""
    SupplyPoint.objects.filter(pk=supply_point.pk).update(
        market_state=SupplyPoint.MarketState.PENDING,
        pending_transfer_id=transfer_id,
    )
    supply_point.market_state = SupplyPoint.MarketState.PENDING
    supply_point.pending_transfer_id = transfer_id


def clear_pending_transfer(supply_point: SupplyPoint, transfer_id) -> None:
    """A transfer ended without registering — release the pending mark,
    but only while it is still this transfer's: a newer pending
    correlation is left untouched."""
    SupplyPoint.objects.filter(
        pk=supply_point.pk,
        market_state=SupplyPoint.MarketState.PENDING,
        pending_transfer_id=transfer_id,
    ).update(
        market_state=SupplyPoint.MarketState.NONE,
        pending_transfer_id=None,
    )


def apply_transfer_outcome(supply_point: SupplyPoint, payload: dict) -> None:
    """Core-side consumer for `market.transfer_completed`: validates the
    versioned envelope's signature fields against this supply point and
    records the registration. The correlation must match the transfer
    currently pending in the database — a stale delivery for an old
    correlation can never overwrite a newer pending or registered
    state. Idempotent: re-delivering the correlation that registered
    the point is a no-op."""
    try:
        correlation = UUID(str(payload["correlation_id"]))
        valid = (
            payload.get("version") == "1"
            and payload.get("nmi") == supply_point.nmi
            and correlation
            and date.fromisoformat(str(payload["effective_date"]))
            and datetime.fromisoformat(str(payload["occurred_at"]))
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("invalid outcome envelope")
    updated = SupplyPoint.objects.filter(
        pk=supply_point.pk,
        market_state=SupplyPoint.MarketState.PENDING,
        pending_transfer_id=correlation,
    ).update(market_state=SupplyPoint.MarketState.REGISTERED)
    if updated:
        return
    current = SupplyPoint.objects.only("market_state", "pending_transfer_id").get(
        pk=supply_point.pk
    )
    if (
        current.market_state == SupplyPoint.MarketState.REGISTERED
        and current.pending_transfer_id == correlation
    ):
        return
    raise ValueError("outcome does not match the pending transfer")
