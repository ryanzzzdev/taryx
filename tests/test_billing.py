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
    CalculationUnavailable,
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
    original = billing_services.lock_inputs

    def gated_lock(*args):
        # Both operations pass validation together, then race for the
        # account lock that serialises input validation through commit.
        barrier.wait(timeout=10)
        return original(*args)

    def go(op):
        close_old_connections()
        try:
            process(op)
        finally:
            close_old_connections()

    with (
        patch.object(billing_services, "lock_inputs", gated_lock),
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
def test_posted_journal_is_sealed_against_new_legs():
    """A balanced or unbalanced append in a later transaction must fail:
    the journal sealed when its creating transaction committed."""
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    invoice = process(admit(account, run)).invoice
    journal = invoice.journal_entries.get()
    with pytest.raises(IntegrityError, match="sealed"), transaction.atomic():
        Posting.objects.create(journal=journal, account_code="1100", debit=Decimal("1.00"))
    with pytest.raises(IntegrityError, match="sealed"), transaction.atomic():
        Posting.objects.create(journal=journal, account_code="1100", debit=Decimal("1.00"))
        Posting.objects.create(journal=journal, account_code="4000", credit=Decimal("1.00"))


@pytest.mark.django_db(transaction=True)
def test_unbalanced_journal_rejected_at_commit():
    """Postings for a new journal are admitted in its creating transaction,
    but the deferred balance check still rejects an unbalanced set."""
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    op = admit(account, run)
    invoice = process(op).invoice
    # The deferred balance trigger fires at commit — inside atomic's exit.
    with pytest.raises(IntegrityError, match="not balanced"), transaction.atomic():
        journal = JournalEntry.objects.create(
            invoice=invoice, operation=op, memo="unbalanced probe"
        )
        Posting.objects.create(journal=journal, account_code="1100", debit=Decimal("5.00"))
        Posting.objects.create(journal=journal, account_code="4000", debit=Decimal("3.00"))


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


@pytest.mark.django_db(transaction=True)
def test_open_quarantine_blocks_issuance():
    """Open quarantines are part of the pinned inputs: a conflict arriving
    after rating changes the digest even when selected records stand."""
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    ingest_nem12_content(load("day1_rev2.nem12"), "day1_rev2.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    op = admit(account, run)
    ingest_nem12_content(load("day1_conflict.nem12"), "day1_conflict.nem12")
    result = process(op)
    assert result.status == "stale"
    assert Invoice.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_revision_committed_during_issuance_goes_stale():
    """A revision committing between the digest check and issuance is
    caught by locked revalidation — never issued on superseded inputs."""
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    op = admit(account, run)

    def resolver(*args):
        digest = digest_resolver(*args)

        def change():
            close_old_connections()
            try:
                ingest_nem12_content(load("day1_rev1.nem12"), "day1_rev1.nem12")
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(change).result(timeout=15)
        return digest

    result = process_operation(op.operation_id, digest_resolver=resolver)
    assert result.status == "stale"
    assert Invoice.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_net_credit_invoice_posts_to_correct_sides():
    """High-export days rate negative; the receivable leg must post to the
    credit side rather than a negative debit."""
    seed_demo_data()
    lines = load("day1_base.nem12").decode().splitlines()
    export = False
    for i, line in enumerate(lines):
        if line.startswith("200,"):
            export = line.split(",")[4] == "B1"
        if line.startswith("300,") and export:
            row = line.split(",")
            row[2:50] = ["10"] * 48
            lines[i] = ",".join(row)
    ingest_nem12_content("\n".join(lines).encode(), "high-export.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, DAY, NEXT, **KWARGS)
    assert run.total < 0
    op = process(admit(account, run))
    assert op.status == "complete"
    legs = {
        p.account_code: (p.debit, p.credit) for p in op.invoice.journal_entries.get().postings.all()
    }
    assert legs[ACC_RECEIVABLE] == (Decimal("0.00"), abs(run.total))


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_key_admission_resolves_one_winner():
    """Racing identical admissions share one durable operation and outbox."""
    seed_demo_data()
    ingest_nem12_content(load("day1_base.nem12"), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(account, DAY, NEXT, **KWARGS)

    def go():
        close_old_connections()
        try:
            return admit_issue(account, DAY, NEXT, run, "OP-SAME")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=20) for f in [pool.submit(go) for _ in range(2)]]
    assert {r.operation_id for r in results} == {"OP-SAME"}
    assert BillingOperation.objects.count() == 1
    assert OutboxEvent.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_empty_journal_rejected_at_commit(billed_account):
    """A journal header reaching commit without legs violates the >=2
    balanced-posting invariant — and the seal means it could never be
    completed later, so the deferred check also runs on journal insert."""
    account, run = billed_account
    op = process(admit(account, run))
    with pytest.raises(IntegrityError), transaction.atomic():
        JournalEntry.objects.create(invoice=op.invoice, operation=op, memo="empty")


@pytest.mark.django_db(transaction=True)
def test_failed_outbox_event_does_not_starve_later_work(billed_account):
    """One failing event records its retry state and is skipped — it
    cannot block recovery of later independent events."""
    account, run = billed_account
    failed = admit_issue(
        account,
        DAY,
        NEXT,
        run,
        "OP-LEGACY",
        routing_resolver=lambda _account: ("legacy_only", 0),
    )
    healthy = admit(account, run, op="OP-HEALTHY")

    def unavailable(_op):
        raise CalculationUnavailable("unavailable", "synthetic legacy outage")

    for _ in range(2):
        with pytest.raises(CalculationUnavailable):
            drain_outbox(digest_resolver=digest_resolver, legacy_calculator=unavailable)
    failed.refresh_from_db()
    healthy.refresh_from_db()
    event = OutboxEvent.objects.get(operation=failed)
    assert failed.status == "pending"
    assert event.attempts == 2 and event.last_error
    assert healthy.status == "complete"


@pytest.mark.django_db(transaction=True)
def test_outbox_recovers_after_many_failed_attempts(billed_account):
    """Failed events are never excluded: after any number of transient
    failures the next ordinary drain retries and completes them."""
    account, run = billed_account
    op = admit_issue(
        account,
        DAY,
        NEXT,
        run,
        "OP-EXHAUSTED",
        routing_resolver=lambda _account: ("legacy_only", 0),
    )

    def unavailable(_op):
        raise CalculationUnavailable("unavailable", "temporary outage")

    for _ in range(10):
        with pytest.raises(CalculationUnavailable):
            drain_outbox(digest_resolver=digest_resolver, legacy_calculator=unavailable)
    op.refresh_from_db()
    assert op.status == "pending" and op.outbox_event.attempts == 10

    def recovered(_op):
        return {
            "charge": Decimal("8.30"),
            "export": Decimal("0.48"),
            "net": Decimal("7.82"),
            "gst": Decimal("0.83"),
            "total": Decimal("8.65"),
        }

    drain_outbox(digest_resolver=digest_resolver, legacy_calculator=recovered)
    op.refresh_from_db()
    assert op.status == "complete"
