# Taryx operator walkthrough — M5 measured portfolio release

Date: 2026-11-13
Audience: a developer evaluating Taryx for the first time.
Recording: [demo-journey.txt](demo-journey.txt) — a real terminal
typescript of `scripts/demo-journey.sh` on a clean stack (reproduce
with `NO_COLOR=1 script -qec "bash scripts/demo-journey.sh" out.txt`).

## What Taryx is

A local, reproducible model of an Australian retail-energy billing
backend: versioned NEM12 meter ingestion, deterministic rating, an
immutable balanced financial ledger, explainable corrections, a guarded
legacy→new migration path, two isolated fictional retailers, a bounded
market-transfer workflow — all instrumented for recovery and
correlated diagnostics. Django/PostgreSQL/Celery/RabbitMQ modular
monolith with a React portal.

## Setup (verified path)

```text
make install        # uv sync (locked) + npm ci
make up             # build + start the two-client stack
make check          # lint, mypy, import contracts, pytest, web build
```

`db-init` / `broker-init` jobs provision both clients idempotently
on every `up`. Seed once per client:

```text
docker compose exec api    python manage.py seed_client
docker compose exec api-sg python manage.py seed_client
```

Reset is `make reset` (drops the pgdata/broker volumes) then `make up`.
Both were exercised in the recording (step 1 does an equivalent
`down -v` + `up`). Kubernetes delivery has its own
[README](../../../deploy/k8s/README.md) — `install.sh` /
`reset.sh` on a fresh kind cluster.

## The journey (as recorded)

1. **Clean setup** — `down -v` + `up`; 11 containers healthy.
2. **Seed** — three deterministic accounts per client, three demo
   users (viewer/operator/approver), `Legacy Cohort A` in
   `legacy_only`.
3. **Metering** — `day1_base.nem12` publishes 96 intervals over E1+B1.
4. **Billing** — `rate_account` → `bill_account` → `INV-000001`
   with a balanced journal.
5. **Correction** — `day1_rev1.nem12` revises one interval; re-rate +
   re-bill yields `ADJ-000001` (`delta_total 0.10`) linked to the
   original invoice — no edit-in-place.
6. **Migration** — `run_comparison` on both cohort members shows real
   diffs (ACC-001 ×4, ACC-003 ×1 — GST heritage policy); scoped
   `decide_discrepancy` decisions clear the gate;
   `legacy_only → shadow → new_only` (revision 1 → 3).
7. **Post-cutover billing** — `INV-000002` for ACC-003 carries
   `calculation_source=new` next to ACC-001's `legacy` — the routing
   switch is visible on the invoice row.
8. **Client isolation** — southgrid seeds its own estate; its DB role
   is denied `CONNECT` to the aurora database (verified live).
9. **Market** — a transfer request goes `draft → submitted →
   completed` through the deterministic counterparty; the core-owned
   outbox consumer marks the NMI `registered`.
10. **Diagnostics** — `/metrics` exposes bounded enum-label counters;
    worker logs are JSON carrying `task_id`/`task_name` on every line.

## What the evidence shows beyond the journey

- **Recovery** ([fault-campaign](fault-campaign.md)): SIGKILL before
  financial commit leaves nothing; SIGKILL after commit keeps the
  invoice without duplicating; broker outage, duplicate delivery,
  abandoned lease, market-adapter restart and billing-under-market-
  outage all recover through durable state — 7/7 real-process
  scenarios.
- **Budgets** ([portfolio-run](portfolio-run.md),
  [budget-runs](budget-runs.md)): R1 ingest 32.9–51.4 s across three
  runs (≤ 90 s); 100-account billing batch 8.3 s, p95 0.386 s per
  account (≤ 2 s, ≤ 5 min); SIGKILL recovery 6.8 s (≤ 60 s); API p95
  ≤ 34.7 ms during ingest (≤ 500 ms); peak stack 5.76 GiB (≤ 8 GiB);
  queue depth 0.
- **Kubernetes** ([kubernetes](kubernetes.md)): fresh-cluster install,
  migration gate observed holding pods in `Init`, failed-rollout stall
  with the old replica still serving, NetworkPolicy and credential
  denials, forced + graceful worker termination, two-worker scaling
  with duplicate-delivery idempotency, and a real reset→reinstall.
- **Audit** ([verification-audit](verification-audit.md)): every
  matrix row, gate, milestone exit and doc link checked.

## Limitations and exclusions

- **Revision ingest is slow.** A whole-estate same-day revision file
  (the update path, not fresh delivery) measured ~450 s — over the 90 s
  budget. Outside the declared R1 workload; recorded in
  [portfolio-run.md](portfolio-run.md). Equal-stamp revisions
  correctly quarantine per interval.
- **Local only.** No hosted-CI green run is claimed; no cloud
  deployment (AWS/Terraform/ArgoCD), no public hosting.
- **Simulated market.** The counterparty is the deterministic in-repo
  simulator — no live AEMO connection, no MSATS/aseXML conformance
  claim.
- **Small-machine budgets.** R1 (180k intervals) is the frozen
  acceptance profile; the 1000-account rung is a declared capacity
  experiment, not measured here.
- **NEM12/R1 profile only** — 30-minute E1/B1, no other formats or
  interval lengths.
- **Not production-ready**: no HA, no real certificates, demo
  credentials throughout, single-machine topology.
- **M5 independent review is still pending** at the time of writing —
  this walkthrough is implementation evidence, not the verdict.
