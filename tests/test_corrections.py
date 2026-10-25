"""Successive corrections and adjustments (TAR-008).

Every correction reconciles revised liability against the net liability
already recognised by the invoice and all posted adjustments. Issued
documents are never mutated; repeated corrections are no-ops; zero-delta
corrections retain audit evidence without money movement.
"""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import Error as DbError
from django.db import close_old_connections, connection, transaction

from taryx.composition.tasks import digest_resolver
from taryx.core.accounts.models import Account
from taryx.core.accounts.seed import seed_demo_data
from taryx.core.billing.models import (
    Adjustment,
    BillingOperation,
    Invoice,
    JournalEntry,
)
from taryx.core.billing.services import (
    ACC_ENERGY_REVENUE,
    ACC_GST_LIABILITY,
    ACC_RECEIVABLE,
    admit_issue,
    drain_outbox,
    process_operation,
)
from taryx.core.metering.ingestion import ingest_nem12_content
from taryx.core.pricing.services import rate_account
from taryx.territories.au_nem.tariffs import GST_RATE, POLICY_IDENTITY, TARIFFS

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nem12"
KWARGS = {"tariffs": TARIFFS, "gst_rate": GST_RATE, "policy_identity": POLICY_IDENTITY}
DAY = date(2026, 3, 2)
NEXT = date(2026, 3, 3)


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def bill(account, op):
    run = rate_account(account, DAY, NEXT, **KWARGS)
    return process_operation(
        admit_issue(account, DAY, NEXT, run, op).operation_id,
        digest_resolver=digest_resolver,
    )


def recognised(invoice):
    return sum(a.delta_total for a in invoice.adjustments.all()) + invoice.total


@pytest.fixture
def issued(db):
    """ACC-001 billed for the base day-1 selection: $8.65."""
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    op = bill(account, "OP-ISSUE")
    assert op.status == "complete"
    return account, op.invoice


@pytest.mark.django_db
def test_successive_revisions_reconcile_against_recognised(issued):
    """RC-09 chain: +$0.10 debit then -$0.07 credit vs recognised, never
    vs the original total."""
    account, invoice = issued
    assert invoice.total == Decimal("8.65")

    ingest_nem12_content(load("day1_rev1.nem12"), "day1_rev1.nem12")  # 0.5->0.8 @10:00
    op1 = bill(account, "OP-C1")
    adj1 = op1.adjustment
    assert op1.status == "complete" and adj1.generation == 1
    assert adj1.number.startswith("ADJ-")
    assert adj1.delta_total == Decimal("0.10")
    assert recognised(invoice) == Decimal("8.75")
    legs = {(p.account_code, p.debit, p.credit) for p in adj1.journal_entries.get().postings.all()}
    # +0.09 energy (incl. supply basis), +0.01 GST, +0.10 receivable, export unchanged.
    assert legs == {
        (ACC_RECEIVABLE, Decimal("0.10"), Decimal("0")),
        (ACC_ENERGY_REVENUE, Decimal("0"), Decimal("0.09")),
        (ACC_GST_LIABILITY, Decimal("0"), Decimal("0.01")),
    }

    ingest_nem12_content(load("day1_rev2.nem12"), "day1_rev2.nem12")  # 0.8->0.6 @10:00
    op2 = bill(account, "OP-C2")
    adj2 = op2.adjustment
    assert adj2.generation == 2
    assert adj2.delta_total == Decimal("-0.07")  # 8.68 - 8.75 recognised
    assert recognised(invoice) == Decimal("8.68")
    legs = {(p.account_code, p.debit, p.credit) for p in adj2.journal_entries.get().postings.all()}
    assert legs == {
        (ACC_RECEIVABLE, Decimal("0"), Decimal("0.07")),
        (ACC_ENERGY_REVENUE, Decimal("0.06"), Decimal("0")),
        (ACC_GST_LIABILITY, Decimal("0.01"), Decimal("0")),
    }
    # Issued documents untouched.
    assert Invoice.objects.get(pk=invoice.pk).total == Decimal("8.65")


@pytest.mark.django_db
def test_repeated_correction_is_noop(issued):
    account, invoice = issued
    ingest_nem12_content(load("day1_rev1.nem12"), "day1_rev1.nem12")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    op1 = process_operation(
        admit_issue(account, DAY, NEXT, run, "OP-R1").operation_id,
        digest_resolver=digest_resolver,
    )
    # Same revised run re-admitted under a new operation id: same digest.
    run2 = rate_account(account, DAY, NEXT, **KWARGS)
    op2 = process_operation(
        admit_issue(account, DAY, NEXT, run2, "OP-R2").operation_id,
        digest_resolver=digest_resolver,
    )
    assert op2.status == "complete"
    assert op2.adjustment_id == op1.adjustment_id
    assert Adjustment.objects.count() == 1
    assert JournalEntry.objects.count() == 2  # issuance + one correction


@pytest.mark.django_db
def test_zero_delta_correction_keeps_audit_without_journal(issued):
    """A different input selection producing identical money posts an
    audit adjustment with no postings."""
    account, invoice = issued
    # B1 re-sent with newer MSATS timestamps but identical values:
    # selection (and digest) change, liability does not.
    ingest_nem12_content(load("day1_b1_resend.nem12"), "day1_b1_resend.nem12")
    op = bill(account, "OP-Z")
    assert op.status == "complete"
    adj = op.adjustment
    assert adj is not None and adj.delta_total == Decimal("0.00")
    assert adj.journal_entries.count() == 0
    assert recognised(invoice) == Decimal("8.65")


@pytest.mark.django_db
def test_correction_goes_stale_when_selection_moves_again(issued):
    """An admitted correction pinned to a superseded selection cannot post."""
    account, invoice = issued
    ingest_nem12_content(load("day1_rev1.nem12"), "day1_rev1.nem12")
    op = bill(account, "OP-C1")
    assert op.adjustment.delta_total == Decimal("0.10")

    run = rate_account(account, DAY, NEXT, **KWARGS)  # pins rev1 digest
    op2 = admit_issue(account, DAY, NEXT, run, "OP-C2")
    ingest_nem12_content(load("day1_rev2.nem12"), "day1_rev2.nem12")  # selection moves
    result = process_operation(op2.operation_id, digest_resolver=digest_resolver)
    assert result.status == "stale"
    assert Adjustment.objects.count() == 1
    assert recognised(invoice) == Decimal("8.75")


@pytest.mark.django_db
def test_correction_of_reverted_selection_posts_back(issued):
    """Reverting to the originally billed data posts a credit back to the
    original liability — an adjustment, never a new or mutated invoice."""
    account, invoice = issued
    ingest_nem12_content(load("day1_rev1.nem12"), "day1_rev1.nem12")
    op1 = bill(account, "OP-C1")
    assert op1.adjustment.delta_total == Decimal("0.10")

    # E1 re-sent at the original values under newer timestamps: selection
    # reverts to 0.5 kWh but through a different source record, so the
    # digest differs from the invoice's — this is a correction, not a
    # duplicate issuance.
    ingest_nem12_content(load("day1_rev3_revert.nem12"), "day1_rev3_revert.nem12")
    op = bill(account, "OP-REVERT")
    assert op.status == "complete"
    adj = op.adjustment
    assert adj is not None and adj.generation == 2
    assert adj.delta_total == Decimal("-0.10")
    assert adj.input_digest != invoice.input_digest
    assert recognised(invoice) == Decimal("8.65")
    assert Invoice.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_racing_corrections_serialize_generations():
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    op0 = bill(account, "OP-ISSUE")
    invoice = op0.invoice
    for name in ("day1_rev1.nem12", "day1_rev2.nem12"):
        ingest_nem12_content(load(name), name)

    # Two ops admitted on distinct runs of the same revised selection:
    # whichever locks the invoice first posts generation 1; the other
    # repeats against the same recognised digest and links it.
    run_a = rate_account(account, DAY, NEXT, **KWARGS)
    run_b = rate_account(account, DAY, NEXT, **KWARGS)
    ops = [
        admit_issue(account, DAY, NEXT, run, op_id)
        for run, op_id in ((run_a, "OP-RA"), (run_b, "OP-RB"))
    ]

    def go(op):
        close_old_connections()
        try:
            process_operation(op.operation_id, digest_resolver=digest_resolver)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(go, ops))

    assert Adjustment.objects.filter(invoice=invoice).count() == 1
    assert recognised(invoice) == Decimal("8.68")
    assert {BillingOperation.objects.get(pk=o.pk).status for o in ops} == {"complete"}
    assert {BillingOperation.objects.get(pk=o.pk).adjustment_id for o in ops} == {
        Adjustment.objects.get(invoice=invoice).id
    }


@pytest.mark.django_db(transaction=True)
def test_adjustments_are_immutable_at_database(issued):
    account, invoice = issued
    ingest_nem12_content(load("day1_rev1.nem12"), "day1_rev1.nem12")
    adj = bill(account, "OP-C1").adjustment
    with pytest.raises(DbError, match="immutable"), transaction.atomic():
        Adjustment.objects.filter(pk=adj.pk).update(delta_total=0)
    with (
        pytest.raises(DbError, match="immutable"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM billing_adjustment WHERE id = %s", [adj.pk])


@pytest.mark.django_db(transaction=True)
def test_worker_killed_mid_correction_leaves_no_effect(tmp_path):
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    bill(account, "OP-ISSUE")
    ingest_nem12_content(load("day1_rev1.nem12"), "day1_rev1.nem12")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    op = admit_issue(account, DAY, NEXT, run, "OP-CRASH")

    env = {
        **os.environ,
        "POSTGRES_DB": "test_taryx",
        "TARYX_BILLING_CRASH": "before_commit",
        "DJANGO_SETTINGS_MODULE": "taryx.config.settings",
    }
    proc = subprocess.run(
        [sys.executable, "manage.py", "drain_outbox"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    close_old_connections()
    assert Adjustment.objects.count() == 0
    assert BillingOperation.objects.get(pk=op.pk).status == "pending"

    drain_outbox(digest_resolver=digest_resolver)
    assert Adjustment.objects.count() == 1
    assert BillingOperation.objects.get(pk=op.pk).status == "complete"
    drain_outbox(digest_resolver=digest_resolver)  # redelivery safe
    assert Adjustment.objects.count() == 1
