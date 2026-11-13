# M5 verification audit — matrix, gates, exits, links

Date: 2026-11-13
Scope: audit of the [verification matrix](../../features/verification.md#evidence-matrix),
open gates ([blockers](../../blockers.md)), milestone exit reviews
([roadmap](../../roadmap.md)) and intra-project document links.
Auditor: Devin (implementation agent — the independent M5 review is
still owed; this audit does not replace it).

## Evidence matrix

| Matrix row | Owning task | Status | Evidence |
| --- | --- | --- | --- |
| Fresh workspace, enforced module boundaries | TAR-003 | Done ✅ | `make check` (locked uv sync + npm ci; import-boundary check keeps 2 contracts and rejects the deliberate core→interface probe); M1 approval |
| Tariff/time/numeric profile | TAR-004 | Done ✅ | feature docs frozen; BLK-003 budgets frozen in [metering-and-rating](../../features/metering-and-rating.md) |
| Meter revision selection | TAR-005 | Done ✅ | real-Postgres ingestion tests incl. conflict/out-of-order fixtures (`tests/test_metering*.py`); M1 approval |
| Deterministic rating | TAR-006 | Done ✅ | expected-value fixtures (`tests/fixtures/nem12/expected.json`), Decimal assertions; M1 approval |
| Atomic issuance + adjustments | TAR-007, TAR-008 | Done ✅ | M2 approval; balance checks in suite; [fault campaign](fault-campaign.md) s1/s2/s4 |
| Core operator journey | TAR-009 | Done ✅ | portal + GraphQL flow with permission negatives; M2 approval scope |
| Legacy characterisation | TAR-010 | Done ✅ | M3 approval; `docs/project/evidence/m3/` probes |
| Safe shadow and cutover | TAR-011, TAR-012 | Done ✅ | M3 approval at `64ace7d`; gate-deadlock and cutover-race probes |
| Two isolated clients | TAR-013 | Done ✅ | M4 approval at `98fad76`; same-image digest evidence; credential/vhost probes |
| External workflow | TAR-014, TAR-015 | Done ✅ | M4 approval at `98fad76`; [fault campaign](fault-campaign.md) s6 (adapter restart) + s7 (billing-under-market-outage) closed the allocated M4 exit items |
| Recovery and diagnostics | TAR-016 | Done ✅ | [diagnostics](diagnostics.md), [fault-campaign](fault-campaign.md) (7/7 real-process scenarios), [budget-runs](budget-runs.md) |
| Kubernetes delivery | TAR-017 | Done ✅ | [kubernetes](kubernetes.md): fresh kind install, migration gate (Init held until Job Complete), **failed-rollout stall** (Init:Error, old replica kept serving), boundaries, forced/graceful termination, scaling + duplicate deliveries, reset |
| Measured portfolio demonstration | TAR-018 | This task | [portfolio-run](portfolio-run.md), [demo recording](demo-journey.txt), [walkthrough](walkthrough.md) |

## Frozen-budget summary (declared in metering-and-rating.md)

| Budget | Frozen | Measured | Result |
| --- | --- | --- | --- |
| Ingest R1 end-to-end | ≤ 90 s | 32.9 s (Apr), 48.2 s (May), 51.4 s (Jun) | PASS |
| Billing per account p95 | ≤ 2 s | 0.386 s (n=100, 30-day periods) | PASS |
| R1 billing batch | ≤ 5 min | 8.3 s (100 accounts, admit→issue) | PASS |
| API read p95 during ingest | ≤ 500 ms | 23.1 ms (`/healthz`), 34.7 ms (`/metrics`) | PASS |
| Worker SIGKILL recovery | ≤ 60 s | 6.8 s | PASS |
| Financial effect per operation | exactly one | 100 ops → 100 invoices, 0 unbalanced journals; duplicates → no extra effect | PASS |
| Stack memory during R1 | ≤ 8 GiB | 5.76 GiB fresh-ingest peak; 7.26 GiB revision peak | PASS |
| Queue growth | bounded | depth 0 sampled through batch + ingests | PASS |

Known measured gap (recorded, outside the declared workload):
whole-estate *same-day revision* ingest — 445.5 s / 458.9 s, 7.26 GiB
peak. See [portfolio-run.md](portfolio-run.md#known-gap--same-day-mass-revision-measured-not-budgeted).

## Open gates

BLK-001 (metering/tariff profile), BLK-002 (market interaction
contract), BLK-003 (workload + budgets): all **Resolved** in
[blockers](../../blockers.md). No open gates remain.

## Milestone exits

| Milestone | Independent verdict | SHA |
| --- | --- | --- |
| M1 metering | APPROVED | `e8fda0c` |
| M2 billing | APPROVED | `2704f11` |
| M3 migration | APPROVED | `64ace7d` |
| M4 code | APPROVED | `98fad76` |
| M5 | **pending independent review** — implementation complete, review session owed | — |

## Document links

Automated sweep 2026-11-13: every relative Markdown link under `docs/`
resolves (five links repaired during this audit — one in
`backlog.md`, two in `evidence/m3/m3-exit-review.md`, one each in
`evidence/m1/m1-exit-review.md` and `evidence/m2/m2-independent-review.md`).

## README / setup verification

`README.md` commands verified 2026-11-13: `make install/up/check/down/
reset` targets all exist and were exercised — `make check` fully green
(234 backend + 6 frontend, lint, mypy, import contracts, frontend
build); `docker compose down -v` + `up` clean setup reproduced twice by
the recorded journey; all published endpoints answer
(portal 5174/5175 `200`, api 8001/8002 `/healthz` `200`, sims
18090–18093 `200`).

## Claims boundary

- **Local results only.** No hosted CI run is claimed — `.github/workflows/ci.yml`
  exists but has no recorded green run in this evidence set.
- **No cloud deployment.** The kind cluster is local-only; no AWS,
  Terraform, ArgoCD or public hosting is claimed or implied.
- **No live-market conformance.** The market boundary is a
  deterministic in-repo simulator; no AEMO/MSATS/aseXML conformance or
  real counterparty is claimed.
- **No production SLA.** Budgets are the frozen local acceptance
  profile on this workstation, not a production guarantee.
