"""Celery tasks wiring configured territory policy into core services."""

from celery import shared_task

from taryx.core.accounts.models import Account
from taryx.core.billing.services import drain_outbox, process_operation
from taryx.core.pricing.services import compute_input_digest
from taryx.territories.au_nem.tariffs import GST_RATE, POLICY_IDENTITY, TARIFFS


def digest_resolver(account: Account, period_start, period_end) -> str:
    return compute_input_digest(
        account,
        period_start,
        period_end,
        tariffs=TARIFFS,
        gst_rate=GST_RATE,
        policy_identity=POLICY_IDENTITY,
    )


@shared_task(name="taryx.billing.process_operation")
def process_billing_operation(operation_id: str) -> str:
    return process_operation(operation_id, digest_resolver=digest_resolver).status


@shared_task(name="taryx.billing.drain_outbox")
def drain_outbox_task() -> int:
    return len(drain_outbox(digest_resolver=digest_resolver))
