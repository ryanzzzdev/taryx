"""Account-side services — the validating core consumer for bounded
integration outcomes. The market adapter's drain never writes core
state itself; it hands the verified envelope here."""

from taryx.core.accounts.models import SupplyPoint


def begin_transfer(supply_point: SupplyPoint) -> None:
    """Mark the supply point as having a transfer in flight."""
    supply_point.market_state = SupplyPoint.MarketState.PENDING
    supply_point.save(update_fields=["market_state"])


def clear_pending_transfer(supply_point: SupplyPoint) -> None:
    """A transfer ended without registering — release the pending mark."""
    if supply_point.market_state == SupplyPoint.MarketState.PENDING:
        supply_point.market_state = SupplyPoint.MarketState.NONE
        supply_point.save(update_fields=["market_state"])


def apply_transfer_outcome(supply_point: SupplyPoint, payload: dict) -> None:
    """Core-side consumer for `market.transfer_completed`: validates the
    versioned envelope's signature fields against this supply point and
    records the registration. Idempotent — re-delivery is a no-op."""
    if payload.get("version") != "1" or payload.get("nmi") != supply_point.nmi:
        raise ValueError("invalid outcome envelope")
    if supply_point.market_state != SupplyPoint.MarketState.REGISTERED:
        supply_point.market_state = SupplyPoint.MarketState.REGISTERED
        supply_point.save(update_fields=["market_state"])
