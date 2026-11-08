"""Round-two checks for recovery after retry exhaustion and authoritative explanation."""

from contextlib import suppress
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from m1_foundation_probes import DAY, END, setup_run

from taryx.composition.tasks import digest_resolver
from taryx.core.billing.services import (
    CalculationUnavailable,
    admit_issue,
    drain_outbox,
    process_operation,
)
from taryx.interfaces.graphql.schema import schema

pytestmark = pytest.mark.django_db(transaction=True)


def test_f2_outbox_recovers_after_transient_failure_budget_exhausted():
    account, run = setup_run()
    op = admit_issue(
        account, DAY, END, run, "exhausted", routing_resolver=lambda account: ("legacy_only", 0)
    )

    def unavailable(op):
        raise CalculationUnavailable("unavailable", "temporary outage")

    for _ in range(10):
        with suppress(CalculationUnavailable):
            drain_outbox(digest_resolver=digest_resolver, legacy_calculator=unavailable)
    op.refresh_from_db()
    assert op.status == "pending"
    assert op.outbox_event.attempts == 10

    def recovered(op):
        return {
            "charge": Decimal("8.30"),
            "export": Decimal("0.48"),
            "net": Decimal("7.82"),
            "gst": Decimal("0.83"),
            "total": Decimal("8.65"),
        }

    drain_outbox(digest_resolver=digest_resolver, legacy_calculator=recovered)
    op.refresh_from_db()
    assert op.status == "complete", "recovered dependency is never retried by normal drain"


def test_f3_portal_explanation_reconciles_to_authoritative_invoice():
    account, run = setup_run()
    op = admit_issue(
        account,
        DAY,
        END,
        run,
        "legacy-explanation",
        routing_resolver=lambda account: ("legacy_only", 0),
    )

    # Valid, balanced legacy result deliberately differs from the new-engine run.
    def legacy(op):
        return {
            "charge": Decimal("8.30"),
            "export": Decimal("0.45"),
            "net": Decimal("7.85"),
            "gst": Decimal("0.83"),
            "total": Decimal("8.68"),
        }

    process_operation(op.operation_id, digest_resolver=digest_resolver, legacy_calculator=legacy)
    user = get_user_model().objects.create_user(username="review-viewer")
    result = schema.execute(
        '{invoices(reference:"ACC-001"){total calculationSource ratingRun{lines{amount gst}}}}',
        context_value=SimpleNamespace(user=user),
    )
    assert not result.errors, result.errors
    invoice = result.data["invoices"][0]
    assert invoice["calculationSource"] == "legacy"
    explained = sum(
        Decimal(line["amount"]) + Decimal(line["gst"]) for line in invoice["ratingRun"]["lines"]
    )
    assert explained == Decimal(invoice["total"]), "portal renders new-engine lines for legacy bill"
