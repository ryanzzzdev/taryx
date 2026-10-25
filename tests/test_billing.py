"""Durable issuance and balanced posting (TAR-007).

Covers admission idempotency, outbox recovery, atomic issuance,
generation uniqueness under racing operations, staleness preconditions,
database-level balance and immutability enforcement, and a real
subprocess kill before commit.
"""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import Error as DbError
from django.db import close_old_connections, connection, transaction
from django.db.utils import IntegrityError

from taryx.composition.tasks import digest_resolver, process_billing_operation
from taryx.core.accounts.models import Account
from taryx.core.accounts.seed import seed_demo_data
from taryx.core.billing import services as billing_services
from taryx.core.billing.models import (
    BillingOperation,
    Invoice,
    JournalEntry,
    OutboxEvent,
    Posting,
)
from taryx.core.billing.services import (
    ACC_ENERGY_REVENUE,
    ACC_EXPORT_CREDIT,
    ACC_GST_LIABILITY,
    ACC_RECEIVABLE,
    AdmissionError,
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


@pytest.fixture
def billed_account(db):
    """Seeded ACC-001 (E1+B1, T-FLAT-FIT) rated over one day → RC-03 $8.65."""
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    return account, run


def admit(account, run, op="OP-1"):
    return admit_issue(account, DAY, NEXT, run, op)


def process(op):
    return process_operation(op.operation_id, digest_resolver=digest_resolver)


@pytest.mark.django_db
def test_admission_is_durable_and_idempotent(billed_account):
    account, run = billed_account
    op = admit(account, run)
    assert op.status == "pending"
    assert OutboxEvent.objects.filter(operation=op, delivered_at__isnull=True).exists()
    again = admit(account, run)
    assert again.pk == op.pk and BillingOperation.objects.count() == 1


@pytest.mark.django_db
def test_same_operation_id_different_payload_conflicts(billed_account):
    account, run = billed_account
    admit(account, run)
    run2 = rate_account(account, DAY, NEXT, **KWARGS)  # same digest, different run id
    with pytest.raises(AdmissionError) as exc:
        admit(account, run2)
    assert exc.value.code == "operation_conflict"


@pytest.mark.django_db
def test_issuance_writes_invoice_and_balanced_journal(billed_account):
    account, run = billed_account
    op = process(admit(account, run))
    assert op.status == "complete"
    invoice = op.invoice
    assert invoice.total == Decimal("8.65") and invoice.number.startswith("INV-")
    journal = JournalEntry.objects.get(invoice=invoice)
    legs = {(p.account_code, p.debit, p.credit) for p in journal.postings.all()}
    assert legs == {
        (ACC_RECEIVABLE, Decimal("8.65"), Decimal("0")),
        (ACC_ENERGY_REVENUE, Decimal("0"), Decimal("8.30")),
        (ACC_EXPORT_CREDIT, Decimal("0.48"), Decimal("0")),
        (ACC_GST_LIABILITY, Decimal("0"), Decimal("0.83")),
    }
    assert OutboxEvent.objects.get(operation=op).delivered_at is not None


@pytest.mark.django_db
def test_duplicate_delivery_is_noop(billed_account):
    account, run = billed_account
    op = admit(account, run)
    process(op)
    process(op)
    assert Invoice.objects.count() == 1
    assert JournalEntry.objects.count() == 1


@pytest.mark.django_db
def test_outbox_drain_recovers_pending_work(billed_account):
    """Admission without dispatch (broker down) stays pending; drain completes it."""
    account, run = billed_account
    op = admit(account, run)
    processed = drain_outbox(digest_resolver=digest_resolver)
    assert [o.operation_id for o in processed] == [op.operation_id]
    assert BillingOperation.objects.get(pk=op.pk).status == "complete"
    assert Invoice.objects.count() == 1


@pytest.mark.django_db
def test_enqueue_failure_leaves_durable_pending_work(billed_account):
    account, run = billed_account
    with patch.object(
        process_billing_operation, "delay", side_effect=ConnectionError("broker down")
    ):
        call_command("bill_account", "ACC-001", "2026-03-02", "2026-03-03", "--op", "OP-BR")
    op = BillingOperation.objects.get(operation_id="OP-BR")
    assert op.status == "pending"
    drain_outbox(digest_resolver=digest_resolver)
    assert BillingOperation.objects.get(pk=op.pk).status == "complete"


@pytest.mark.django_db
def test_changed_inputs_mark_run_stale(billed_account):
    account, run = billed_account
    op = admit(account, run)
    ingest_nem12_content(load("day1_rev1.nem12"), "day1_rev1.nem12")  # new selection
    result = process(op)
    assert result.status == "stale"
    assert result.invoice_id is None
    assert Invoice.objects.count() == 0
    # Re-rating against the new selection issues normally.
    run2 = rate_account(account, DAY, NEXT, **KWARGS)
    op2 = process(admit(account, run2, "OP-2"))
    assert op2.status == "complete"
    assert op2.invoice.total == Decimal("8.75")


@pytest.mark.django_db(transaction=True)
def test_racing_operations_cannot_double_issue():
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    ops = [admit(account, run, f"OP-R{i}") for i in range(2)]
    barrier = Barrier(2)
    original = billing_services._issue

    def issue(op):
        barrier.wait(timeout=10)
        return original(op)

    def go(op):
        close_old_connections()
        try:
            process(op)
        finally:
            close_old_connections()

    with (
        patch.object(billing_services, "_issue", issue),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        futures = [pool.submit(go, op) for op in ops]
        for f in futures:
            f.result(timeout=30)
    assert Invoice.objects.count() == 1
    invoice = Invoice.objects.get()
    assert {BillingOperation.objects.get(pk=o.pk).invoice_id for o in ops} == {invoice.id}
    assert {BillingOperation.objects.get(pk=o.pk).status for o in ops} == {"complete"}


@pytest.mark.django_db(transaction=True)
def test_financial_documents_are_immutable():
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    invoice = process(admit(account, run)).invoice
    journal = invoice.journal_entries.get()
    posting = journal.postings.first()

    with pytest.raises(DbError, match="immutable"), transaction.atomic():
        Invoice.objects.filter(pk=invoice.pk).update(total=0)
    # Raw SQL bypasses ORM PROTECT: the database trigger itself must reject.
    with (
        pytest.raises(DbError, match="immutable"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM billing_invoice WHERE id = %s", [invoice.pk])
    with pytest.raises(DbError, match="immutable"), transaction.atomic():
        JournalEntry.objects.filter(pk=journal.pk).update(memo="tampered")
    with pytest.raises(DbError, match="immutable"), transaction.atomic():
        posting.delete()


@pytest.mark.django_db(transaction=True)
def test_unbalanced_journal_rejected_at_commit():
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    invoice = process(admit(account, run)).invoice
    journal = invoice.journal_entries.get()
    with pytest.raises(IntegrityError, match="not balanced"), transaction.atomic():
        Posting.objects.create(journal=journal, account_code="1100", debit=Decimal("1.00"))


@pytest.mark.django_db(transaction=True)
def test_worker_killed_before_commit_leaves_no_effect(tmp_path):
    """A real subprocess dies inside the issuing transaction; redelivery
    produces exactly one financial effect."""
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    op = admit(account, run)

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
    assert Invoice.objects.count() == 0
    assert BillingOperation.objects.get(pk=op.pk).status == "pending"

    drain_outbox(digest_resolver=digest_resolver)
    assert Invoice.objects.count() == 1
    assert BillingOperation.objects.get(pk=op.pk).status == "complete"

    # Redelivery after commit is harmless.
    drain_outbox(digest_resolver=digest_resolver)
    assert Invoice.objects.count() == 1
