"""Independent foundation regressions; run explicitly with pytest -c pyproject.toml."""

from contextlib import suppress
from datetime import date
from pathlib import Path

import pytest
from django.db import IntegrityError, transaction

from taryx.composition.tasks import digest_resolver
from taryx.core.accounts.models import Account
from taryx.core.accounts.seed import seed_demo_data
from taryx.core.billing.models import JournalEntry
from taryx.core.billing.services import (
    CalculationUnavailable,
    admit_issue,
    drain_outbox,
    process_operation,
)
from taryx.core.metering.ingestion import ingest_nem12_content
from taryx.core.pricing.services import rate_account
from taryx.territories.au_nem.tariffs import GST_RATE, POLICY_IDENTITY, TARIFFS

pytestmark = pytest.mark.django_db(transaction=True)
DAY, END = date(2026, 3, 2), date(2026, 3, 3)


def setup_run():
    seed_demo_data()
    fixture = Path(__file__).resolve().parents[3] / "tests/fixtures/nem12/day1_base.nem12"
    ingest_nem12_content(fixture.read_bytes(), fixture.name)
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(
        account, DAY, END, tariffs=TARIFFS, gst_rate=GST_RATE, policy_identity=POLICY_IDENTITY
    )
    return account, run


def test_f1_empty_journal_must_be_rejected_at_commit():
    account, run = setup_run()
    op = admit_issue(account, DAY, END, run, "review-empty")
    op = process_operation(op.operation_id, digest_resolver=digest_resolver)
    with pytest.raises(IntegrityError), transaction.atomic():
        JournalEntry.objects.create(invoice=op.invoice, operation=op, memo="empty probe")


def test_f2_failed_event_must_not_starve_later_recoverable_work():
    account, run = setup_run()
    failed = admit_issue(
        account,
        DAY,
        END,
        run,
        "review-unavailable",
        routing_resolver=lambda account: ("legacy_only", 0),
    )
    healthy = admit_issue(account, DAY, END, run, "review-healthy")

    def unavailable(op):
        raise CalculationUnavailable("unavailable", "synthetic legacy outage")

    # Even if the drain reports the error, independent events must progress.
    for _ in range(2):
        with suppress(CalculationUnavailable):
            drain_outbox(digest_resolver=digest_resolver, legacy_calculator=unavailable)
    failed.refresh_from_db()
    healthy.refresh_from_db()
    assert failed.status == "pending"
    assert healthy.status == "complete", "earliest failing event starves the healthy event"
