#!/usr/bin/env bash
# TAR-018 operator journey — narrated end-to-end run on a clean stack.
# Covers: setup/reset -> metering -> billing -> correction -> migration
# cutover -> client isolation -> market transfer -> diagnostics.
# Recorded via: script -qec "bash scripts/demo-journey.sh" recording.txt
set -uo pipefail
cd "$(dirname "$0")/.."

api()   { docker compose exec -T api   python manage.py "$@"; }
apisg() { docker compose exec -T api-sg python manage.py "$@"; }
shell()   { api shell -c "$1"; }
shellsg() { apisg shell -c "$1"; }
psqlq() { docker compose exec -T db psql -U taryx_app -d taryx -Atc "$1"; }
banner() { printf '\n=== %s ===\n' "$1"; }
pause() { sleep "${DEMO_PAUSE:-1}"; }

banner "1. CLEAN SETUP — fresh volumes, full stack"
docker compose down -v >/dev/null 2>&1
docker compose up -d --wait db broker legacy market >/dev/null 2>&1 || docker compose up -d db broker legacy market
sleep 8
docker compose up -d --wait api api-sg worker worker-sg legacy-sg market-sg web web-sg >/dev/null 2>&1 || docker compose up -d
sleep 10
docker compose ps --format '{{.Name}} {{.Status}}'
pause

banner "2. SEED — deterministic demo estate (3 accounts, users, cohort)"
api seed_demo
apisg seed_client
pause

banner "3. METERING — NEM12 ingestion, two channels"
docker compose exec -T api sh -c 'mkdir -p /tmp/fix && cat > /tmp/fix/day1.nem12' < tests/fixtures/nem12/day1_base.nem12
api ingest_nem12 /tmp/fix/day1.nem12
psqlq "SELECT c.suffix, count(*) FROM metering_intervalrecord r JOIN accounts_meterchannel c ON c.id=r.channel_id GROUP BY 1 ORDER BY 1"
pause

banner "4. RATING + BILLING — 2026-03-02, ACC-001"
api rate_account ACC-001 2026-03-02 2026-03-03
api bill_account ACC-001 2026-03-02 2026-03-03 --op demo-bill-1
sleep 4
psqlq "SELECT i.number, i.total, count(p.id) AS postings, sum(p.debit)=sum(p.credit) AS balanced FROM billing_invoice i JOIN billing_journalentry j ON j.invoice_id=i.id JOIN billing_posting p ON p.journal_id=j.id GROUP BY i.number, i.total"
pause

banner "5. CORRECTION — revised interval file arrives; re-rate and re-bill"
docker compose exec -T api sh -c 'cat > /tmp/fix/day1_rev1.nem12' < tests/fixtures/nem12/day1_rev1.nem12
api ingest_nem12 /tmp/fix/day1_rev1.nem12
api rate_account ACC-001 2026-03-02 2026-03-03
api bill_account ACC-001 2026-03-02 2026-03-03 --op demo-bill-1-rev
sleep 4
psqlq "SELECT a.number, a.delta_total, a.calculation_source FROM billing_adjustment a ORDER BY a.id DESC LIMIT 1"
psqlq "SELECT count(*) FILTER (WHERE abs(debit_total-credit_total) > 0.001) AS unbalanced FROM (SELECT j.id, sum(p.debit) debit_total, sum(p.credit) credit_total FROM billing_journalentry j JOIN billing_posting p ON p.journal_id=j.id GROUP BY j.id) t"
pause

banner "6. MIGRATION — shadow comparison, decisions, cutover"
docker compose exec -T api sh -c 'cat > /tmp/fix/acc3.nem12' < tests/fixtures/nem12/acc3_heritage_day.nem12
api ingest_nem12 /tmp/fix/acc3.nem12
shell '
from datetime import date
from django.contrib.auth import get_user_model
from taryx.composition.policy import policy
from taryx.core.accounts.models import Account
from taryx.core.pricing.services import rate_account
from taryx.core.migration.models import Cohort
from taryx.core.migration.services import (
    run_comparison, evaluation_blockers, decide_discrepancy, transition_cohort,
)
p = policy()
gate = dict(tariffs=p.TARIFFS, gst_rate=p.GST_RATE, policy_identity=p.POLICY_IDENTITY)
cohort = Cohort.objects.get(name="Legacy Cohort A")
print(f"cohort: {cohort.name} mode={cohort.routing_mode} rev={cohort.routing_revision}")
actor = get_user_model().objects.get_or_create(username="approver")[0]
for ref in ("ACC-001", "ACC-003"):
    acc = Account.objects.get(reference=ref)
    run = rate_account(acc, date(2026, 3, 2), date(2026, 3, 3), **gate)
    row = run_comparison(run)
    diffs = row.report_json["diffs"]
    print(ref + ": comparison " + row.status + " diffs=" + str(len(diffs)))
    for diff in diffs:
        field = diff["field"]
        decide_discrepancy(
            cohort=cohort, fingerprint=diff["fingerprint"],
            classification=("preserve_client_policy" if field in ("gst", "gst_total")
                            else "approved_defect_correction"),
            actor=actor, reason=ref + " " + field + " reviewed in demo",
        )
print("blockers:", evaluation_blockers(cohort, **gate))
cohort = transition_cohort(cohort.id, "shadow", cohort.routing_revision, actor, reason="start shadow billing", **gate)
print("entered shadow mode rev=" + str(cohort.routing_revision))
cohort = transition_cohort(cohort.id, "new_only", cohort.routing_revision, actor, reason="demo cutover", **gate)
print(f"cutover: mode={cohort.routing_mode} rev={cohort.routing_revision}")
'
pause

banner "7. POST-CUTOVER BILLING — ACC-003 under new routing"
api bill_account ACC-003 2026-03-02 2026-03-03 --op demo-cohort-bill
sleep 4
psqlq "SELECT a.reference, i.number, i.calculation_source FROM billing_invoice i JOIN accounts_account a ON a.id=i.account_id ORDER BY i.id"
pause

banner "8. CLIENT ISOLATION — southgrid stack, own database"
apisg shell -c 'from taryx.core.accounts.models import Account; print("southgrid accounts:", list(Account.objects.values_list("reference", flat=True)))'
docker compose exec -T db psql -U taryx_sg -d taryx -c "SELECT 1" 2>&1 | head -2
pause

banner "9. MARKET — transfer request through the deterministic counterparty"
shell '
from datetime import date
from taryx.core.accounts.models import SupplyPoint
from taryx.core.market.services import request_transfer
from taryx.composition.tasks import market_submit
sp = SupplyPoint.objects.filter(market_state="registered").first() or SupplyPoint.objects.first()
w = request_transfer(sp, date(2026, 3, 20))
print("workflow", w.correlation_id, "state", w.state)
market_submit.delay(str(w.correlation_id))
'
sleep 15  # submit + reconcile + outbox drain (10s beat) must all land
psqlq "SELECT correlation_id, state, attempts FROM market_transferworkflow ORDER BY id DESC LIMIT 1"
psqlq "SELECT nmi, market_state FROM accounts_supplypoint ORDER BY id LIMIT 3"
pause

banner "10. DIAGNOSTICS — metrics surface + correlated logs"
curl -s localhost:8001/metrics | grep -v '^#' | head -8
docker compose logs worker --tail 3 2>/dev/null | head -4
pause

banner "JOURNEY COMPLETE"
psqlq "SELECT (SELECT count(*) FROM billing_invoice)||' invoices, '||(SELECT count(*) FROM billing_adjustment)||' adjustments, '||(SELECT count(*) FROM metering_intervalrecord)||' intervals'"
