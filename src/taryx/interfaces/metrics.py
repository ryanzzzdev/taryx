"""`/metrics` — Prometheus text exposition of durable business counters.

Label sets are the models' own status enums, so cardinality is bounded
by the schema, not by data volume. Everything here reads committed
state, which is exactly what recovery evidence needs: a counter must
never claim an effect the ledger does not show."""

import os

from django.db.models import Count
from django.http import HttpResponse

from taryx.core.billing.models import BillingOperation
from taryx.core.market.models import (
    MarketException,
    MarketInbox,
    MarketOutbox,
    TransferWorkflow,
)


def _by_status(model, field="status") -> dict:
    rows = model.objects.values(field).annotate(n=Count("pk")).order_by(field)
    return {row[field]: row["n"] for row in rows}


def metrics(request):
    """Text-format metrics; unauthenticated like /healthz since the
    values are aggregate counts with no client-confidential payload."""
    lines = [
        "# HELP taryx_billing_operations Billing operations by status.",
        "# TYPE taryx_billing_operations gauge",
    ]
    for status, count in _by_status(BillingOperation).items():
        lines.append(f'taryx_billing_operations{{status="{status}"}} {count}')
    lines += [
        "# HELP taryx_market_workflows Transfer workflows by state.",
        "# TYPE taryx_market_workflows gauge",
    ]
    for state, count in _by_status(TransferWorkflow, "state").items():
        lines.append(f'taryx_market_workflows{{state="{state}"}} {count}')
    lines += [
        "# HELP taryx_market_outbox_pending Market outbox events awaiting delivery.",
        "# TYPE taryx_market_outbox_pending gauge",
        "taryx_market_outbox_pending "
        + str(MarketOutbox.objects.filter(delivered_at__isnull=True).count()),
        "# HELP taryx_market_exceptions_total Parked market exceptions.",
        "# TYPE taryx_market_exceptions_total gauge",
        f"taryx_market_exceptions_total {MarketException.objects.count()}",
        "# HELP taryx_market_inbox_total Deduplicated inbound callbacks.",
        "# TYPE taryx_market_inbox_total gauge",
        f"taryx_market_inbox_total {MarketInbox.objects.count()}",
        "# HELP taryx_build_info Deployment identity.",
        "# TYPE taryx_build_info gauge",
        f'taryx_build_info{{client="{os.environ.get("TARYX_CLIENT", "unknown")}"}} 1',
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain; version=0.0.4")
