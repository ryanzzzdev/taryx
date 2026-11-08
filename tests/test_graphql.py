"""Operator GraphQL contract (TAR-009).

Session auth, role enforcement (viewer/operator/approver), the
ingest→rate→bill→poll journey through durable operations, and audit
entries for consequential actions. Mutations report domain failures via
stable payload codes; GraphQL-level errors only signal transport/schema
problems.
"""

import json
from datetime import date as dd
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


@pytest.mark.django_db
def test_retry_same_request_after_rerating_returns_original_operation(seeded):
    """A retry of an identical request after re-rating must resolve the
    already-admitted operation, not conflict on the newer hidden payload."""
    client = Client()
    login(client, "operator")
    gql(
        client,
        "mutation($f:String!,$c:String!){ingestNem12(filename:$f,content:$c){ok}}",
        f="day1_base.nem12",
        c=load("day1_base.nem12"),
    )
    bill = (
        'mutation($o:String!){billAccount(reference:"ACC-001",'
        'periodStart:"2026-03-02",periodEnd:"2026-03-03",'
        "operationId:$o){ok code operation{operationId}}}"
    )
    gql(
        client,
        'mutation{rateAccount(reference:"ACC-001",'
        'periodStart:"2026-03-02",periodEnd:"2026-03-03"){ok}}',
    )
    first = gql(client, bill, o="STABLE-1")["data"]["billAccount"]
    assert first["ok"]
    # A second rating run exists; the identical retry still resolves.
    gql(
        client,
        'mutation{rateAccount(reference:"ACC-001",'
        'periodStart:"2026-03-02",periodEnd:"2026-03-03"){ok}}',
    )
    retry = gql(client, bill, o="STABLE-1")["data"]["billAccount"]
    assert retry["ok"], retry
    assert retry["operation"]["operationId"] == first["operation"]["operationId"]
    # The same key for a genuinely different request still conflicts.
    conflict = gql(
        client,
        'mutation($o:String!){billAccount(reference:"ACC-002",'
        'periodStart:"2026-03-02",periodEnd:"2026-03-03",'
        "operationId:$o){ok code}}",
        o="STABLE-1",
    )["data"]["billAccount"]
    assert conflict == {"ok": False, "code": "operation_conflict"}


@pytest.mark.django_db
def test_csrf_enforced_with_trusted_dev_origin(seeded):
    """Fresh-browser behaviour: POST without a CSRF cookie/token is 403,
    a safe GET bootstraps the cookie, and an untrusted Origin is refused."""
    client = Client(enforce_csrf_checks=True)
    origin = {"HTTP_ORIGIN": "http://localhost:5174"}

    denied = client.post(
        "/graphql",
        data=json.dumps({"query": "{me{username}}"}),
        content_type="application/json",
        **origin,
    )
    assert denied.status_code == 403

    # Safe request bootstraps the csrftoken cookie (ensure_csrf_cookie).
    assert client.get("/graphql", {"query": "{__typename}"}).status_code == 200
    token = client.cookies["csrftoken"].value

    ok = client.post(
        "/graphql",
        data=json.dumps({"query": "{me{username}}"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
        **origin,
    )
    assert ok.status_code == 200

    bad_origin = client.post(
        "/graphql",
        data=json.dumps({"query": "{me{username}}"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
        HTTP_ORIGIN="http://evil.example",
    )
    assert bad_origin.status_code == 403


@pytest.mark.django_db
def test_login_rotates_csrf_token(seeded):
    """After login the old CSRF secret is invalid; the rotated cookie's
    token must be echoed instead (the portal reads it fresh each call)."""
    client = Client(enforce_csrf_checks=True)
    origin = {"HTTP_ORIGIN": "http://localhost:5174"}
    client.get("/graphql", {"query": "{__typename}"})
    old_token = client.cookies["csrftoken"].value

    login_query = 'mutation{login(username:"operator",password:"taryx-operator"){ok}}'
    stale = client.post(
        "/graphql",
        data=json.dumps({"query": login_query}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=old_token,
        **origin,
    )
    assert stale.status_code == 200  # login itself succeeds with pre-session token

    new_token = client.cookies["csrftoken"].value
    assert new_token != old_token
    rejected = client.post(
        "/graphql",
        data=json.dumps({"query": "{me{username}}"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=old_token,
        **origin,
    )
    assert rejected.status_code == 403
    accepted = client.post(
        "/graphql",
        data=json.dumps({"query": "{me{username}}"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=new_token,
        **origin,
    )
    assert accepted.status_code == 200


# --- TAR-012: migration journey ------------------------------------------


@pytest.mark.django_db(databases=["default", "shadow"], transaction=True)
def test_migration_journey_permissions_and_guards():
    """Viewer reads evidence; operator decides; approver transitions;
    stale revisions are rejected."""
    from taryx.core.migration.seed import seed_migration_cohort

    seed_demo_data()
    seed_operator_identities()
    cohort = seed_migration_cohort()

    client = Client()
    login(client, "viewer")
    data = gql(client, "{cohorts{name routingMode routingRevision members{reference}}}")
    [c] = data["data"]["cohorts"]
    assert c["name"] == "Legacy Cohort A"
    assert c["routingMode"] == "LEGACY_ONLY"
    assert {m["reference"] for m in c["members"]} == {"ACC-001", "ACC-003"}

    # Viewers cannot decide or transition.
    out = gql(
        client,
        "mutation{decideDiscrepancy(cohortId:" + str(cohort.id) + ',fingerprint:"x",'
        'classification:"preserve_client_policy",reason:"r"){ok code}}',
    )
    assert out["errors"][0]["extensions"]["code"] == "permission_denied"

    login(client, "approver")
    out = gql(
        client,
        'mutation($c:Int!){transitionCohort(cohortId:$c,toMode:"shadow",'
        "expectedRevision:99){ok code}}",
        c=cohort.id,
    )
    assert out["data"]["transitionCohort"] == {
        "ok": False,
        "code": "stale_revision",
    }
    out = gql(
        client,
        'mutation($c:Int!){transitionCohort(cohortId:$c,toMode:"shadow",'
        "expectedRevision:1){ok code cohort{routingMode routingRevision}}}",
        c=cohort.id,
    )
    assert out["data"]["transitionCohort"]["ok"]
    assert out["data"]["transitionCohort"]["cohort"]["routingRevision"] == 2
    assert out["data"]["transitionCohort"]["cohort"]["routingMode"] == "SHADOW"

    # Rollback is permitted; the event log records both transitions.
    out = gql(
        client,
        'mutation($c:Int!){transitionCohort(cohortId:$c,toMode:"legacy_only",'
        "expectedRevision:2){ok}}",
        c=cohort.id,
    )
    assert out["data"]["transitionCohort"]["ok"]
    events = gql(client, "query($c:Int!){cohortEvents(cohortId:$c){action toMode}}", c=cohort.id)[
        "data"
    ]["cohortEvents"]
    assert [e["toMode"] for e in events] == ["legacy_only", "shadow"]

    # In-flight billing blocks any mode change.

    from taryx.core.accounts.models import Account
    from taryx.core.billing.models import BillingOperation
    from taryx.core.metering.ingestion import ingest_nem12_content
    from taryx.core.pricing.services import rate_account
    from taryx.territories.au_nem.tariffs import GST_RATE, POLICY_IDENTITY, TARIFFS

    ingest_nem12_content(load("day1_base.nem12").encode(), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(
        account,
        dd(2026, 3, 2),
        dd(2026, 3, 3),
        tariffs=TARIFFS,
        gst_rate=GST_RATE,
        policy_identity=POLICY_IDENTITY,
    )
    BillingOperation.objects.create(
        operation_id="OP-INFLIGHT",
        account=account,
        period_start=dd(2026, 3, 2),
        period_end=dd(2026, 3, 3),
        rating_run=run,
        payload_sha256="x",
        status="pending",
    )
    out = gql(
        client,
        'mutation($c:Int!){transitionCohort(cohortId:$c,toMode:"shadow",'
        "expectedRevision:3){ok code}}",
        c=cohort.id,
    )
    assert out["data"]["transitionCohort"]["code"] == "in_flight"


@pytest.mark.django_db
def test_invoice_line_items_pin_the_issued_calculation(seeded):
    """The explain journey: an invoice's rating run exposes the pinned
    line items — quantities, rates and basis from the issued generation,
    unaffected by subsequent re-rating."""
    client = Client()
    login(client, "operator")
    gql(
        client,
        "mutation($f:String!,$c:String!){ingestNem12(filename:$f,content:$c){ok}}",
        f="day1_base.nem12",
        c=load("day1_base.nem12"),
    )
    rated = gql(
        client,
        "mutation($r:String!,$s:Date!,$e:Date!){rateAccount(reference:$r,"
        "periodStart:$s,periodEnd:$e){ok run{id inputDigest}}}",
        r="ACC-001",
        s=DAY,
        e=NEXT,
    )
    issued_run = rated["data"]["rateAccount"]["run"]
    gql(
        client,
        "mutation($r:String!,$s:Date!,$e:Date!,$o:String!){billAccount("
        "reference:$r,periodStart:$s,periodEnd:$e,operationId:$o){ok}}",
        r="ACC-001",
        s=DAY,
        e=NEXT,
        o="GQL-EXP-1",
    )
    drain_outbox(digest_resolver=digest_resolver)

    # Subsequent correction inputs create a newer run with a new digest.
    gql(
        client,
        "mutation($f:String!,$c:String!){ingestNem12(filename:$f,content:$c){ok}}",
        f="day1_rev1.nem12",
        c=load("day1_rev1.nem12"),
    )
    rerated = gql(
        client,
        "mutation($r:String!,$s:Date!,$e:Date!){rateAccount(reference:$r,"
        "periodStart:$s,periodEnd:$e){ok run{id inputDigest}}}",
        r="ACC-001",
        s=DAY,
        e=NEXT,
    )
    assert rerated["data"]["rateAccount"]["run"]["id"] != issued_run["id"]

    out = gql(
        client,
        "query($r:String!){invoices(reference:$r){number inputDigest "
        "calculationSource ratingRun{id inputDigest engineVersion "
        "policyIdentity lines{tariffCode element quantity unit rate "
        "amount basis segmentFrom segmentTo}}}}",
        r="ACC-001",
    )
    invoice = out["data"]["invoices"][0]
    pinned = invoice["ratingRun"]
    assert pinned["id"] == issued_run["id"]
    assert pinned["inputDigest"] == issued_run["inputDigest"] == invoice["inputDigest"]
    assert invoice["calculationSource"] == "new"
    assert pinned["lines"], "issued line items must be explainable"
    for line in pinned["lines"]:
        assert line["tariffCode"] and line["basis"] and line["unit"]
        Decimal(line["quantity"]), Decimal(line["rate"]), Decimal(line["amount"])


@pytest.mark.django_db(transaction=True)
def test_legacy_invoice_explanation_reconciles(seeded):
    """A legacy-source invoice explains itself with the authoritative
    legacy figures — never the new-engine comparison run's lines."""
    from taryx.core.accounts.models import Account
    from taryx.core.billing.services import admit_issue, process_operation
    from taryx.core.metering.ingestion import ingest_nem12_content
    from taryx.core.pricing.services import rate_account
    from taryx.territories.au_nem.tariffs import GST_RATE, POLICY_IDENTITY, TARIFFS

    ingest_nem12_content(load("day1_base.nem12").encode(), "day1_base.nem12")
    account = Account.objects.get(reference="ACC-001")
    run = rate_account(
        account,
        dd(2026, 3, 2),
        dd(2026, 3, 3),
        tariffs=TARIFFS,
        gst_rate=GST_RATE,
        policy_identity=POLICY_IDENTITY,
    )
    op = admit_issue(
        account,
        dd(2026, 3, 2),
        dd(2026, 3, 3),
        run,
        "GQL-LEGACY-1",
        routing_resolver=lambda _account: ("legacy_only", 0),
    )

    def legacy(_op):
        return {
            "charge": Decimal("8.30"),
            "export": Decimal("0.45"),
            "net": Decimal("7.85"),
            "gst": Decimal("0.83"),
            "total": Decimal("8.68"),
        }

    process_operation(op.operation_id, digest_resolver=digest_resolver, legacy_calculator=legacy)

    client = Client()
    login(client, "viewer")
    out = gql(
        client,
        "query($r:String!){invoices(reference:$r){total calculationSource "
        "ratingRun{lines{amount gst}}}}",
        r="ACC-001",
    )
    invoice = out["data"]["invoices"][0]
    assert invoice["calculationSource"] == "legacy"
    explained = sum(
        Decimal(line["amount"]) + Decimal(line["gst"]) for line in invoice["ratingRun"]["lines"]
    )
    assert explained == Decimal(invoice["total"]) == Decimal("8.68")
