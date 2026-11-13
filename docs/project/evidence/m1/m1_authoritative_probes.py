"""Round-three probes using the real legacy persistence/issuance path."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from m1_foundation_probes import DAY, END, setup_run

from taryx.composition.tasks import digest_resolver
from taryx.core.billing.services import admit_issue, process_operation
from taryx.core.migration.legacy_adapter import LegacyLine, LegacyResult
from taryx.core.migration.models import LegacyCalculation
from taryx.core.migration.services import calculate_for_billing
from taryx.interfaces.graphql.schema import schema

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "shadow"])


def issue_persisted_legacy():
    account, run = setup_run()
    line = LegacyLine(
        element="import",
        band=None,
        tariff_code="review",
        tariff_version="1",
        agreement_id=1,
        segment_from=DAY,
        segment_to=END,
        quantity=Decimal(1),
        unit="kWh",
        rate=Decimal("7.85"),
        amount=Decimal("7.85"),
        gst=Decimal("0.83"),
        basis="review authoritative line",
    )
    result = LegacyResult(
        engine="legacy",
        engine_version="review-1",
        catalogue_version="review-1",
        snapshot_hash=run.input_digest,
        request_id="review-persisted",
        lines=(line,),
        net=Decimal("7.85"),
        gst=Decimal("0.83"),
        total=Decimal("8.68"),
    )
    op = admit_issue(
        account,
        DAY,
        END,
        run,
        "persisted-legacy",
        routing_resolver=lambda account: ("legacy_only", 0),
    )
    with patch("taryx.core.migration.services.calculate", return_value=result):
        op = process_operation(
            op.operation_id,
            digest_resolver=digest_resolver,
            legacy_calculator=calculate_for_billing,
        )
    assert op.invoice.legacy_calculation_id is not None
    return op.invoice


def test_f3_persisted_legacy_lines_can_be_queried():
    invoice = issue_persisted_legacy()
    user = get_user_model().objects.create_user(username="pinned-viewer")
    result = schema.execute(
        '{invoices(reference:"ACC-001"){total ratingRun{lines{amount gst segmentFrom segmentTo}}}}',
        context_value=SimpleNamespace(user=user),
    )
    assert not result.errors, result.errors
    lines = result.data["invoices"][0]["ratingRun"]["lines"]
    assert sum(Decimal(row["amount"]) + Decimal(row["gst"]) for row in lines) == invoice.total


def test_f4_authoritative_issued_evidence_rejects_mutation():
    invoice = issue_persisted_legacy()
    with pytest.raises(DatabaseError), transaction.atomic(using="shadow"):
        LegacyCalculation.objects.using("shadow").filter(pk=invoice.legacy_calculation_id).update(
            response_json={"lines": []}, total=Decimal("999.00")
        )


def test_f4_authoritative_issued_evidence_rejects_raw_delete():
    """Exercise the new DELETE trigger through the restricted credential,
    bypassing ORM protection and retaining the invoice's reference."""
    from django.db import connections

    invoice = issue_persisted_legacy()
    with (
        pytest.raises(DatabaseError, match="immutable"),
        transaction.atomic(using="shadow"),
        connections["shadow"].cursor() as cursor,
    ):
        cursor.execute(
            "DELETE FROM migration_legacycalculation WHERE id = %s",
            [invoice.legacy_calculation_id],
        )
    assert (
        LegacyCalculation.objects.using("shadow").filter(pk=invoice.legacy_calculation_id).exists()
    )
