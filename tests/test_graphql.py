"""Operator GraphQL contract (TAR-009).

Session auth, role enforcement (viewer/operator/approver), the
ingest→rate→bill→poll journey through durable operations, and audit
entries for consequential actions. Mutations report domain failures via
stable payload codes; GraphQL-level errors only signal transport/schema
problems.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from django.test import Client

from taryx.composition.tasks import digest_resolver
from taryx.core.accounts.seed import seed_demo_data, seed_operator_identities
from taryx.core.audit.models import AuditEntry
from taryx.core.billing.models import Invoice
from taryx.core.billing.services import drain_outbox
from taryx.core.metering.models import CurrentInterval, QuarantinedInterval

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nem12"
DAY = "2026-03-02"
NEXT = "2026-03-03"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture
def seeded(db):
    seed_demo_data()
    seed_operator_identities()


def gql(client: Client, query: str, **variables):
    response = client.post(
        "/graphql",
        data=json.dumps({"query": query, "variables": variables}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content[:500]
    return json.loads(response.content)


def login(client: Client, role: str) -> None:
    result = gql(
        client,
        "mutation($u:String!,$p:String!){login(username:$u,password:$p){ok code user{role}}}",
        u=role,
        p=f"taryx-{role}",
    )
    assert result["data"]["login"]["ok"], result


def test_login_logout_and_me(seeded):
    client = Client()
    assert gql(client, "{me{username role}}")["data"]["me"] is None
    bad = gql(
        client,
        'mutation{login(username:"operator",password:"wrong"){ok code}}',
    )
    assert bad["data"]["login"] == {"ok": False, "code": "invalid_credentials"}
    login(client, "viewer")
    assert gql(client, "{me{username role}}")["data"]["me"] == {
        "username": "viewer",
        "role": "viewer",
    }
    assert gql(client, "mutation{logout{ok}}")["data"]["logout"]["ok"]
    assert gql(client, "{me{username}}")["data"]["me"] is None


def test_anonymous_and_viewer_denied(seeded):
    client = Client()
    # Anonymous: queries rejected with permission_denied.
    result = gql(client, "{accounts{reference}}")
    assert result["data"] is None
    assert result["errors"][0]["extensions"]["code"] == "permission_denied"

    login(client, "viewer")
    # Viewer can query...
    assert gql(client, "{accounts{reference}}")["data"]["accounts"]
    # ...but cannot mutate.
    result = gql(
        client,
        'mutation{ingestNem12(filename:"x",content:"100,NEM12"){ok}}',
    )
    assert result["errors"][0]["extensions"]["code"] == "permission_denied"
    result = gql(
        client,
        'mutation($q:Int!,$r:Int!){resolveQuarantine(quarantineId:$q,recordId:$r,reason:"x"){ok}}',
        q=1,
        r=1,
    )
    assert result["errors"][0]["extensions"]["code"] == "permission_denied"


def test_operator_cannot_resolve_quarantine(seeded, db):
    client = Client()
    login(client, "operator")
    result = gql(
        client,
        'mutation{resolveQuarantine(quarantineId:1,recordId:1,reason:"x"){ok}}',
    )
    assert result["errors"][0]["extensions"]["code"] == "permission_denied"


@pytest.mark.django_db
def test_operator_journey_ingest_rate_bill_poll(seeded):
    client = Client()
    login(client, "operator")

    ing = gql(
        client,
        "mutation($f:String!,$c:String!){ingestNem12(filename:$f,content:$c)"
        "{ok code batch{status acceptedCount quarantinedCount}}}",
        f="day1_base.nem12",
        c=load("day1_base.nem12"),
    )
    batch = ing["data"]["ingestNem12"]["batch"]
    assert batch == {
        "status": "PUBLISHED",
        "acceptedCount": 96,
        "quarantinedCount": 0,
    }

    rated = gql(
        client,
        "mutation($r:String!,$s:Date!,$e:Date!){rateAccount(reference:$r,"
        "periodStart:$s,periodEnd:$e){ok code run{id total inputDigest}}}",
        r="ACC-001",
        s=DAY,
        e=NEXT,
    )
    run = rated["data"]["rateAccount"]["run"]
    assert rated["data"]["rateAccount"]["ok"] and run["total"] == "8.65"

    billed = gql(
        client,
        "mutation($r:String!,$s:Date!,$e:Date!,$o:String!){billAccount("
        "reference:$r,periodStart:$s,periodEnd:$e,operationId:$o)"
        "{ok code operation{operationId status}}}",
        r="ACC-001",
        s=DAY,
        e=NEXT,
        o="GQL-OP-1",
    )
    op = billed["data"]["billAccount"]["operation"]
    assert op["operationId"] == "GQL-OP-1" and op["status"] == "PENDING"

    # No broker in tests: the durable outbox relay completes it, then the
    # same poll the portal performs reports the outcome.
    drain_outbox(digest_resolver=digest_resolver)
    polled = gql(
        client,
        "query($o:String!){billingOperation(operationId:$o)"
        "{operationId status invoice{number total "
        "journalEntries{postings{accountCode debit credit}}}}}",
        o="GQL-OP-1",
    )
    outcome = polled["data"]["billingOperation"]
    assert outcome["status"] == "COMPLETE"
    assert outcome["invoice"]["total"] == "8.65"

    # Idempotent retry with the same operation id returns the outcome.
    again = gql(
        client,
        "mutation($r:String!,$s:Date!,$e:Date!,$o:String!){billAccount("
        "reference:$r,periodStart:$s,periodEnd:$e,operationId:$o){ok code}}",
        r="ACC-001",
        s=DAY,
        e=NEXT,
        o="GQL-OP-1",
    )
    assert again["data"]["billAccount"]["ok"]
    assert Invoice.objects.count() == 1

    # Correction journey: revision ingested, re-rated, billed again →
    # linked adjustment, invoice immutable.
    gql(
        client,
        "mutation($f:String!,$c:String!){ingestNem12(filename:$f,content:$c){ok}}",
        f="day1_rev1.nem12",
        c=load("day1_rev1.nem12"),
    )
    gql(
        client,
        "mutation($r:String!,$s:Date!,$e:Date!){rateAccount(reference:$r,"
        "periodStart:$s,periodEnd:$e){ok}}",
        r="ACC-001",
        s=DAY,
        e=NEXT,
    )
    corrected = gql(
        client,
        "mutation($r:String!,$s:Date!,$e:Date!,$o:String!){billAccount("
        "reference:$r,periodStart:$s,periodEnd:$e,operationId:$o){ok}}",
        r="ACC-001",
        s=DAY,
        e=NEXT,
        o="GQL-OP-2",
    )
    assert corrected["data"]["billAccount"]["ok"]
    drain_outbox(digest_resolver=digest_resolver)
    polled = gql(
        client,
        "query($o:String!){billingOperation(operationId:$o)"
        "{status adjustment{number deltaTotal generation}}}",
        o="GQL-OP-2",
    )
    adj = polled["data"]["billingOperation"]["adjustment"]
    assert adj["deltaTotal"] == "0.10" and adj["generation"] == 1
    assert Invoice.objects.get().total == Decimal("8.65")  # untouched


@pytest.mark.django_db
def test_audit_entries_for_consequential_actions(seeded):
    client = Client()
    login(client, "operator")
    gql(
        client,
        "mutation($f:String!,$c:String!){ingestNem12(filename:$f,content:$c){ok}}",
        f="day1_base.nem12",
        c=load("day1_base.nem12"),
    )
    gql(
        client,
        "mutation($r:String!,$s:Date!,$e:Date!){rateAccount(reference:$r,"
        "periodStart:$s,periodEnd:$e){ok}}",
        r="ACC-001",
        s=DAY,
        e=NEXT,
    )
    gql(
        client,
        "mutation($r:String!,$s:Date!,$e:Date!,$o:String!){billAccount("
        "reference:$r,periodStart:$s,periodEnd:$e,operationId:$o){ok}}",
        r="ACC-001",
        s=DAY,
        e=NEXT,
        o="GQL-AUD",
    )
    actions = set(AuditEntry.objects.values_list("action", flat=True))
    assert {"metering.ingest", "pricing.rate", "billing.admit"} <= actions
    assert AuditEntry.objects.get(action="billing.admit").actor == "operator"


@pytest.mark.django_db
def test_approver_resolves_quarantine(seeded):
    client = Client()
    login(client, "operator")
    # Create a real quarantine: equal-precedence differing values (rev2 vs
    # the conflict fixture tie on quality and timestamps).
    for name in ("day1_rev2.nem12", "day1_conflict.nem12"):
        gql(
            client,
            "mutation($f:String!,$c:String!){ingestNem12(filename:$f,content:$c){ok}}",
            f=name,
            c=load(name),
        )
    quarantine = QuarantinedInterval.objects.get(status="open")
    record = quarantine.candidate_records.first()

    login(client, "approver")
    resolved = gql(
        client,
        "mutation($q:Int!,$r:Int!){resolveQuarantine(quarantineId:$q,recordId:$r,"
        'reason:"retailer-confirmed actual"){ok code quarantine{status}}}',
        q=quarantine.id,
        r=record.id,
    )
    assert resolved["data"]["resolveQuarantine"]["ok"]
    assert resolved["data"]["resolveQuarantine"]["quarantine"]["status"] == "RESOLVED"
    current = CurrentInterval.objects.get(
        channel_id=quarantine.channel_id,
        interval_end_utc=quarantine.interval_end_utc,
    )
    assert current.source_record_id == record.id
    assert AuditEntry.objects.filter(action="metering.resolve_quarantine").exists()


@pytest.mark.django_db
def test_rejected_ingest_reports_stable_code(seeded):
    client = Client()
    login(client, "operator")
    result = gql(
        client,
        "mutation($f:String!,$c:String!){ingestNem12(filename:$f,content:$c)"
        "{ok code batch{status errorCode}}}",
        f="bad_value.nem12",
        c=load("bad_value.nem12"),
    )
    batch = result["data"]["ingestNem12"]["batch"]
    assert batch["status"] == "REJECTED" and batch["errorCode"]
