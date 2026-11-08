"""Account-side services — the validating core consumer for bounded
integration outcomes. The market adapter's drain never writes core
state itself; it hands the verified envelope here."""

from datetime import date, datetime
from uuid import UUID

from taryx.core.accounts.models import SupplyPoint


def begin_transfer(supply_point: SupplyPoint, transfer_id) -> None:
    """Mark the supply point as having `transfer_id` in flight."""
    supply_point.market_state = SupplyPoint.MarketState.PENDING
    supply_point.pending_transfer_id = transfer_id
    supply_point.save(update_fields=["market_state", "pending_transfer_id"])


def clear_pending_transfer(supply_point: SupplyPoint) -> None:
    """A transfer ended without registering — release the pending mark."""
    if supply_point.market_state == SupplyPoint.MarketState.PENDING:
        supply_point.market_state = SupplyPoint.MarketState.NONE
        supply_point.pending_transfer_id = None
        supply_point.save(update_fields=["market_state", "pending_transfer_id"])


def apply_transfer_outcome(supply_point: SupplyPoint, payload: dict) -> None:
    """Core-side consumer for `market.transfer_completed`: validates the
    versioned envelope's signature fields against this supply point and
    records the registration. The correlation must match the transfer
    currently pending here — a stale delivery for an old correlation can
    never overwrite a newer pending or registered state. Idempotent:
    re-delivering the correlation that registered the point is a no-op."""
    try:
        valid = (
            payload.get("version") == "1"
            and payload.get("nmi") == supply_point.nmi
            and UUID(str(payload["correlation_id"]))
            and date.fromisoformat(str(payload["effective_date"]))
            and datetime.fromisoformat(str(payload["occurred_at"]))
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("invalid outcome envelope")
    if (
        supply_point.market_state == SupplyPoint.MarketState.REGISTERED
        and supply_point.pending_transfer_id == UUID(str(payload["correlation_id"]))
    ):
        return
    if supply_point.market_state != SupplyPoint.MarketState.PENDING or str(
        supply_point.pending_transfer_id
    ) != str(payload["correlation_id"]):
        raise ValueError("outcome does not match the pending transfer")
    supply_point.market_state = SupplyPoint.MarketState.REGISTERED
    supply_point.save(update_fields=["market_state"])
