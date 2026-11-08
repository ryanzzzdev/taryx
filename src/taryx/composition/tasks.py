"""Celery tasks wiring configured territory policy into core services."""

from celery import shared_task

from taryx.composition.policy import policy
from taryx.core.accounts.models import Account
from taryx.core.billing.services import (
    CalculationUnavailable,
    drain_outbox,
    process_operation,
)
from taryx.core.migration.legacy_adapter import LegacyFailure
from taryx.core.migration.services import calculate_for_billing, routing_for
from taryx.core.pricing.services import compute_input_digest


def legacy_calculator(op) -> dict:
    """Legacy-routed amounts; transient legacy failures keep the op
    PENDING (in-flight) rather than silently failing or succeeding."""
    try:
        return calculate_for_billing(op)
    except LegacyFailure as exc:
        raise CalculationUnavailable(exc.code, str(exc)) from exc


def digest_resolver(account: Account, period_start, period_end) -> str:
    resolved = policy()
    return compute_input_digest(
        account,
        period_start,
        period_end,
        tariffs=resolved.TARIFFS,
        gst_rate=resolved.GST_RATE,
        policy_identity=resolved.POLICY_IDENTITY,
    )


@shared_task(name="taryx.billing.process_operation")
def process_billing_operation(operation_id: str) -> str:
    return process_operation(
        operation_id,
        digest_resolver=digest_resolver,
        routing_resolver=routing_for,
        legacy_calculator=legacy_calculator,
    ).status


@shared_task(name="taryx.billing.drain_outbox")
def drain_outbox_task() -> int:
    return len(
        drain_outbox(
            digest_resolver=digest_resolver,
            routing_resolver=routing_for,
            legacy_calculator=legacy_calculator,
        )
    )
