# Taryx backlog

Updated: 2026-11-13

Task sections own status; index icons mirror them. See the [documentation guide](documentation-guide.md#task-records).

## Task index

- ✅ [TAR-001 — Establish project-management standards](#tar-001)
- ✅ [TAR-002 — Establish the planning baseline](#tar-002)
- ✅ [TAR-003 — Bootstrap the development workspace](#tar-003)
- ✅ [TAR-004 — Freeze domain and measurement profiles](#tar-004)
- 🚧 [TAR-005 — Implement versioned meter ingestion and fixtures](#tar-005)
- 🚧 [TAR-006 — Implement deterministic itemised rating](#tar-006)
- ✅ [TAR-007 — Implement durable issuance and balanced posting](#tar-007)
- ✅ [TAR-008 — Implement successive corrections and adjustments](#tar-008)
- ✅ [TAR-009 — Deliver the core operator journey](#tar-009)
- ✅ [TAR-010 — Build independent legacy characterisation](#tar-010)
- ✅ [TAR-011 — Implement isolated shadow comparison and gates](#tar-011)
- ✅ [TAR-012 — Deliver operator migration and cutover](#tar-012)
- ✅ [TAR-013 — Demonstrate two isolated client instances](#tar-013)
- ✅ [TAR-014 — Freeze the bounded market workflow](#tar-014)
- ✅ [TAR-015 — Implement market adapter and counterparty simulator](#tar-015)
- ✅ [TAR-016 — Verify recovery and correlated diagnostics](#tar-016)
- ✅ [TAR-017 — Package and verify Kubernetes delivery](#tar-017)
- 📋 [TAR-018 — Measure and present the portfolio release](#tar-018)
- 🚧 [TAR-019 — Evaluate the multi-agent implement/review orchestrator](#tar-019)
- 🚧 [TAR-020 — Design the operator portal UI](#tar-020)

## Delivery notes

M1 metering round-two review (2026-11-08): **approved** at `e8fda0ccfb83c7ddd976771b0166eb5d8beb7ec5`. M1-F1–F4 resolved; TAR-005/TAR-006 completion confirmed with 17 independent probes and full checks passing. [Review](evidence/m1/m1-metering-independent-review.md). Prior billing approval is retained.

Foundation review **approved** at `2704f119c5eba16c284fe93ffd5f86ba5d832847` after the explicitly authorised, resumed fourth round. F1–F4 resolved; 155 backend/6 frontend tests and all 25 preserved probes pass. See [scope, evidence and retained verification gaps](evidence/m1/m1-independent-review.md). Earlier completion and reopening statements below are historical.

M2 re-review findings are remediated and verified (both follow-up probes pass; see the [review](evidence/m2/m2-independent-review.md)). Independent M3 re-review of `f9f21df` found F1–F4; all resolved and re-verified (13/13 preserved probes pass). Next action: close the remaining F2 cutover race in TAR-011/TAR-012 before M4. Later tasks remain Backlog until their dependencies and detailed contracts are ready. Portal/API slices can develop alongside their backend tasks; TAR-009 and TAR-012 own integrated acceptance. Observability hooks and correctness tests accompany implementation; TAR-016 owns the full cross-service campaign, not the first tests.

The architecture and functional scope are the planning baseline; exact schemas, dependency versions and open profiles are refined in their named tasks. Split large tasks into new IDs before starting if necessary; preserve existing history. Next unused ID: TAR-021. M1 metering completion is confirmed by the round-two review above; prior M2 billing approval is retained.

Re-review of `db18588` found one remaining F2 commit-window race; resolved by a shared cohort advisory-lock protocol between cutover and all gate-affecting writers — see the [third remediation addendum](evidence/m3/m3-independent-review.md#third-remediation-addendum--2026-10-25).

<a id="tar-001"></a>

## TAR-001 — Establish project-management standards

- Repository: taryx
- Area: documentation
- Milestone: Documentation setup
- Priority: High
- Status: Done ✅
- Depends on: None
- References: [Contract](documentation-guide.md)

### Outcome

Adapt Cateniq’s portable workflow without copying project history.

### Done when

- Root instructions, portable skill and guide agree on ownership, statuses, UTC journal attribution and atomic records updates.
- README remains intact apart from navigation/status clarification; local links and UTF-8 checks pass.

### Completion evidence

Documentation deliverables created; local link/anchor, dependency, status/index and UTF-8 checks recorded in the [journal](journal/2026-10.md). Files are uncommitted. No application checks apply.

### Notes

Use this workflow for subsequent meaningful work.

<a id="tar-002"></a>

## TAR-002 — Establish the planning baseline

- Repository: taryx
- Area: documentation
- Milestone: Planning baseline
- Priority: High
- Status: Done ✅
- Depends on: TAR-001
- References: [Contract](architecture.md)

### Outcome

Produce a coherent architecture, staged roadmap, feature contracts and initial task sequence.

### Done when

- Architecture separates accepted direction from implementation; features define failure and acceptance cases.
- Milestones have dependencies/exclusions/exits; bounded open gates have owners and unblock actions.
- Task/index/dependency/link consistency checks pass; no runtime completion is claimed.

### Completion evidence

Documentation deliverables created; local link/anchor, dependency, status/index and UTF-8 checks recorded in the [journal](journal/2026-10.md). Files are uncommitted. No application checks apply.

### Notes

Next action: TAR-003; domain profile research can begin alongside bootstrap.

<a id="tar-003"></a>

## TAR-003 — Bootstrap the development workspace

- Repository: taryx
- Area: workspace
- Milestone: M1
- Priority: High
- Status: Done ✅
- Depends on: TAR-002
- References: [Contract](architecture.md)

### Outcome

Create a minimal reproducible API, worker and portal skeleton with real PostgreSQL/RabbitMQ.

### Done when

- Select compatible supported Python/Django/Graphene/Celery and frontend versions from primary documentation; pin/lock dependencies.
- Compose starts API, worker, database and broker; portal connects to a smoke query; startup/config errors are clear.
- Import Linter enforces layer/independence/core-interface contracts and rejects a deliberate violation.
- Minimal CI configuration and locally executed checks cover formatting, typing where useful, tests and import contracts; hosted status is reported separately.
- Document tested install/start/check/reset commands and persistent-volume boundaries.

### Completion evidence

- Pinned Python 3.14 / Django 6.1.2 / graphene-django 3.2.3 / Celery 5.6.3 / psycopg 3.3.6 via uv.lock; React 19.3.1 / Vite 8.3.5 / TypeScript 7.0.2 via package-lock.json.
- `make check` green locally: ruff lint+format, mypy (django-stubs), 5 pytest tests against real PostgreSQL 18.6, import-contract check, web typecheck+build.
- `scripts/check-import-boundaries.sh`: 3 contracts KEPT; deliberate core→interfaces probe rejected.
- Compose stack verified running: `/healthz` ok, GraphQL `ping`/`version` via API and via portal Vite proxy, `taryx.smoke.ping` task executed on worker through RabbitMQ 4.3.7.
- Host ports offset (db 55432, amqp 5673, mgmt 15673, api 8001, web 5174) to coexist with sibling stacks; PG18 volume layout fix applied.
- `.github/workflows/ci.yml` added; hosted run not yet executed.

### Notes

Celery remote control disabled (`worker_enable_remote_control=False`): kombu pidbox declares transient non-exclusive queues, removed in RabbitMQ 4. Revisit if M5 ops scenarios need inspect/revoke broadcasts.

<a id="tar-004"></a>

## TAR-004 — Freeze domain and measurement profiles

- Repository: taryx
- Area: verification
- Milestone: M1
- Priority: High
- Status: Done ✅
- Depends on: TAR-003
- References: [Contract](features/metering-and-rating.md)

### Outcome

Resolve the supported meter/tariff/time profile and independent reference cases before building the engine.

### Done when

- Close BLK-001 with authoritative format references, supported record subset, revision/quality precedence, time conventions, unit/tax/rounding rules and explicit exclusions.
- Create independently calculated expected cases including time/effective-date boundaries and invalid inputs.
- Close BLK-003 with reference hardware, required workload, resource limits and latency/throughput/recovery budgets measured from the bootstrap baseline.

### Completion evidence

- BLK-001/BLK-003 resolved 2026-10-25 in blockers.md; frozen profile appended to features/metering-and-rating.md with linked AEMO sources (MDFF v2.7, Metrology Part B, EMMS DM v5.4, EDGE Part A).
- Independent hand-computed reference cases in features/rating-reference-cases.md (RC-01..RC-09) covering flat/TOU/export/boundary/leap/DST/revision/invalid/adjustment.
- Baseline measured on running bootstrap: 14c/30Gi host, ~1.2 GiB idle stack, /healthz ~18 ms, ping ~5.5 ms; R1 workload and budgets frozen; R2 labelled optional.
- Documentation-only task; no application verification applies beyond doc link/UTF-8 checks.

### Notes

Corrected after the [independent M1 review](evidence/m1/m1-exit-review.md): QMM quality methods, ranged/tiling 400 records, lexical value and reason-code rules frozen per MDFF v2.7; fixtures regenerated to the real format. BLK-001 re-resolved.

<a id="tar-005"></a>

## TAR-005 — Implement versioned meter ingestion and fixtures

- Repository: taryx
- Area: metering
- Milestone: M1
- Priority: High
- Status: Done ✅
- Depends on: TAR-003, TAR-004
- References: [Contract](features/metering-and-rating.md)

### Outcome

Ingest reproducible synthetic batches into versioned PostgreSQL metering history.

### Done when

- Seed deterministic accounts, agreements and raw meter fixtures with independent expected results.
- Validate/stage batches; duplicate, out-of-order, corrected and conflicting readings obey the frozen selection/visibility contract.
- Malformed/unsupported/incomplete data has explicit outcomes; source evidence is retained.
- Integration checks pass in PostgreSQL and M1 exit evidence is recorded.

### Completion evidence

- accounts + metering models with migrations: IngestionBatch (hash dedupe, DUPLICATE inspectability via partial unique), IntervalRecord (raw revisions retained), CurrentInterval (deterministic winner), QuarantinedInterval (equal-precedence conflicts).
- NEM12 parser enforces frozen subset: 100/200/300/400/900 records, NEM12 only, kWh, 5/30-min, E*/B1, A/S/E/F + V-method 400s, ascending dates; stable error codes.
- Selection = quality A>F>S>E then MSATS/Update timestamps; ties with different values quarantine; batch atomic stage+publish.
- 15 deterministic fixtures + hand-derived expected.json; 16 new tests against real PostgreSQL 18.6 — 21 total passing; verified again via `docker compose exec api manage.py seed_demo/ingest_nem12` (96 intervals published, revision applied).
- `channel_coverage` reports expected/selected/quarantined and blocks completeness on gaps or open quarantine.

### Notes

Remediated after the [independent M1 review](evidence/m1/m1-exit-review.md): two-phase selection with per-interval locked re-evaluation, savepoint duplicate recovery (published and rejected), encoding/lexical/row-shape validation, and quarantine resolution by unambiguous newer winners. All ten review probes pass; regressions folded into tests/. Next action: TAR-006.


2026-11-08 metering review: reopened at `230dc0f1078243e3448ecc145c842228b22cca8c` for M1-F1–F3; remediated same day — repeated-200 metadata now validated (`conflicting_200`), repeated channel/days reject as `repeated_interval` before insertion, and equivalent re-enveloped revisions keep incumbent selection/version. All probes folded into `tests/`; see [M1 findings and probes](evidence/m1/m1-metering-independent-review.md). Previous evidence above is historical.

Round-two independent review: **approved** at `e8fda0ccfb83c7ddd976771b0166eb5d8beb7ec5`; M1-F1–F3 verified resolved. 17 independent probes and full make check pass (159 backend/6 frontend). Earlier reopening statements are historical; see [review](evidence/m1/m1-metering-independent-review.md).

<a id="tar-006"></a>

## TAR-006 — Implement deterministic itemised rating

- Repository: taryx
- Area: pricing
- Milestone: M2
- Priority: High
- Status: Done ✅
- Depends on: TAR-005
- References: [Contract](features/metering-and-rating.md)

### Outcome

Calculate supported supply/import/export charges from immutable snapshots.

### Done when

- Decimal calculations and rounding match independent reference cases.
- Agreement/tariff changes and time boundaries are explicit; gaps prevent rating/issuance.
- Output records input identities, quantities, rates, rounding and engine/policy versions; replay is deterministic.

### Completion evidence

Implementation and historical verification are recorded below. Round-two independent metering review: M1-F4 verified resolved; see the [review and reproduction](evidence/m1/m1-metering-independent-review.md).

### Notes

Implemented: pure engine in src/taryx/core/pricing/engine.py (separately testable), pinned RatingRun/RatingLine artifacts with input digest, fictional catalogue in src/taryx/territories/au_nem/tariffs.py injected via composition, rate_account command. RC-01..06 verified; coverage gaps, quarantines and agreement faults are explicit errors; replay deterministic. Next action: TAR-007.

Reopened 2026-10-25 by the [independent M2 review](evidence/m2/m2-independent-review.md). Prior evidence remains historical.

Remediated 2026-10-25 (R5): RatingRun.input_snapshot now retains the exact digest payload (interval selections, agreements, tariff specs, open quarantines, versions) so published calculations reconstruct without trusting mutable metadata; rating runs/lines and interval records are immutable at the database boundary (pricing 0002, metering 0003). Reconstruction and immutability regressions in tests/test_pricing.py; the review's mutation probe passes.

Independent re-review of `de0e08d`: reopened for remaining R5 findings; see [review](evidence/m2/m2-independent-review.md). Original checks pass; two follow-up rating probes failed.

Re-remediated 2026-10-25: RatingLine membership is sealed via the same transaction-local open-flag mechanism as journals (pricing 0003) — a published run cannot gain lines; tariff band time-windows (and other calculation-affecting inputs) are serialised into the digest payload/snapshot so a window-only change repins. Both follow-up probes pass; regressions folded into tests/test_pricing.py.


2026-11-08 metering review: reopened at `230dc0f1078243e3448ecc145c842228b22cca8c`; see [M1 findings and probes](evidence/m1/m1-metering-independent-review.md). Resolve M1-F4 inconsistent rating snapshot coverage and rerun independent probes before completion. Previous evidence above is historical.

Round-two independent review: **approved** at `e8fda0ccfb83c7ddd976771b0166eb5d8beb7ec5`; M1-F4 verified resolved. 17 independent probes and full make check pass (159 backend/6 frontend). Earlier reopening statements are historical; see [review](evidence/m1/m1-metering-independent-review.md).

<a id="tar-007"></a>

## TAR-007 — Implement durable issuance and balanced posting

- Repository: taryx
- Area: billing
- Milestone: M2
- Priority: High
- Status: Done ✅
- Depends on: TAR-006
- References: [Contract](features/billing-and-ledger.md)

### Outcome

Admit billing durably and atomically issue one invoice/journal per business generation.

### Done when

- Operation/outbox admission survives broker downtime; duplicate publication/consumption is safe.
- Freeze and implement bill-generation keys, locks/version preconditions and journal-balance enforcement including runtime permissions.
- Concurrent requests with identical and different operation IDs cannot double-issue; conflicting payload reuse is rejected.
- Real PostgreSQL and worker/broker tests cover commit/ack boundaries, balance rejection and forbidden mutation.

### Completion evidence

Implemented: BillingOperation admission (durable, idempotent by operation_id, conflicting payload reuse rejected), outbox event per operation, atomic issuance of one Invoice + JournalEntry + Postings per account/period generation, Postgres triggers enforcing journal balance and financial-document immutability (raw-SQL delete/update rejected at the database boundary, independent of ORM PROTECT), staleness precondition via pinned rating input digest. 11 tests in tests/test_billing.py cover idempotent admission, conflict rejection, racing operation IDs, duplicate delivery, outbox recovery, changed-input staleness, trigger balance/immutability rejection, and a real-subprocess worker-kill-before-commit leaving no financial effect. make check green (77 tests). Verified live in Compose: bill_account admission -> Celery worker issuance via RabbitMQ (INV-000001, total 8.75, balanced 9.23 Dr = 9.23 Cr across receivables/revenue/export-credit/GST), idempotent retry returned existing outcome, outbox drained safely.

### Notes

Runtime permission boundary is Postgres triggers plus transaction-scoped issuance; the Celery task enqueues at admission and the drain_outbox command relays pending events after outage. Next action: TAR-008.

Reopened 2026-10-25 by the [independent M2 review](evidence/m2/m2-independent-review.md). Prior evidence remains historical.

Remediated 2026-10-25 (R2/R3/R4/R6): open quarantines now feed the input digest; a locked final revalidation (account row + digest inputs under a shared-revision lock protocol — ingestion publish and quarantine resolution take the same account lock first) re-verifies inputs before commit; sign-aware issuance legs post net-credit bills to the correct side and the racing-issuance catch only covers the generation uniqueness key; a transaction-local open-journal flag seals posted journals against appended legs (billing 0004); the GraphQL mutation resolves an existing operation by key before selecting a run, and concurrent same-key admission resolves the winner via savepoint. All six probes pass; regressions in tests/test_billing.py, tests/test_pricing.py and tests/test_graphql.py.

Reopened 2026-11-08 by the [foundation re-review](evidence/m1/m1-independent-review.md) of `c88b722f30526d8c57aef7ff89634ecd8a1fa983` (user-labelled M1; canonical M2). F1 empty-journal enforcement and F2 outbox failure isolation require remediation; both independent PostgreSQL probes fail. Next: fix the database commit check and starvation-safe recovery, then rerun probes and required checks.

Remediated 2026-11-08 (F1/F2): a second deferred constraint trigger on `billing_journalentry` INSERT applies the balanced-posting check at commit — an empty journal is rejected and the seal guarantees it can never be completed later (billing 0008). `drain_outbox` isolates failures per event: retry state (`attempts`/`last_error`) is recorded on the outbox row, later events still process, and events past `max_attempts` stop being selected so a full failing batch cannot starve the drain. Both probes pass and are folded into tests/test_billing.py.

Round-two independent review of `c270a322` (2026-11-08): F1 is independently verified resolved, but F2 remains open: ten transient failures permanently exclude the pending event from normal recovery. Add fair retries or a supported observable requeue path. [Review and failing follow-up probes](evidence/m1/m1-independent-review.md). Required checks pass (151 backend/6 frontend); 20 preserved probes pass and two follow-ups fail.

Re-remediated 2026-11-08 (round-2 F2): the attempt cap is removed — pending events are never excluded; selection orders by `attempts` then `created_at` so chronic failures sink below fresh work yet are always retried, letting a recovered dependency complete on the next ordinary drain. Both follow-up probes pass and are folded into tests/test_billing.py.

Round-three independent review at `e809640` (2026-11-08): F1/F2 resolved. F4: newly pinned authoritative LegacyCalculation remains mutable under shadow credentials; freeze issued evidence and protect its reference before claiming immutable provenance. [Review/probes](evidence/m1/m1-independent-review.md): required checks pass, 22 preserved probes pass, two new probes fail.

Re-remediated 2026-11-08 (F3/F4): persisted legacy lines use flat `segment_from`/`segment_to` keys — the resolver now reads them, so real pinned evidence renders. `migration_legacycalculation` gains a BEFORE UPDATE/DELETE immutability trigger (migration 0004), matching the invoice/journal boundary; a shadow-credential mutation of pinned evidence is rejected by the database. Both probes pass and are folded into tests/test_migration.py.

Independent round-four confirmation (2026-11-08) at `2704f119`: **approved** for this foundation slice. Empty-journal enforcement, admission/issuance regressions, outbox recovery and immutable authoritative evidence (UPDATE and raw DELETE) verified. Required checks and all 25 preserved probes pass; see [review](evidence/m1/m1-independent-review.md) for scope and remaining operational verification gaps.

<a id="tar-008"></a>

## TAR-008 — Implement successive corrections and adjustments

- Repository: taryx
- Area: billing
- Milestone: M2
- Priority: High
- Status: Done ✅
- Depends on: TAR-007
- References: [Contract](features/billing-and-ledger.md)

### Outcome

Reconcile revised liability against all previously recognised liability without changing issued records.

### Done when

- Corrected data identifies affected periods and generates traceable debit/credit or zero-delta outcomes.
- Repeated and successive revisions do not duplicate prior adjustments.
- Concurrent revisions/stale calculations and interrupted adjustment posting preserve the intended recognised generation.

### Completion evidence

Implemented: immutable Adjustment documents (number sequence, per-invoice generation, digest uniqueness) appended under the invoice row lock; deltas reconcile the revised run against recognised liability derived from the journal ledger (revenue/GST credit-positive, receivable/export debit-positive) — never re-subtracting the original total. Signed legs post only for nonzero deltas; zero-delta corrections persist the adjustment without a journal. Repeated corrections return the recognised document; runs pinned to a superseded selection go stale; journals trace to the posting operation and adjustment. Migration 0003 backfills journal.operation with the immutability trigger suspended for that statement only (required on populated databases). 8 tests in tests/test_corrections.py cover the RC-09 chain (+0.10 then -0.07 vs recognised), repeated/zero-delta/stale/racing corrections, revert-to-original, database immutability and a real-subprocess worker kill mid-correction. make check green (85 tests). Verified live in Compose: invoice 8.75 -> ADJ-000001 -0.07 -> ADJ-000002 -0.03 restoring 8.65 via the real worker.

### Notes

Correction triggering is operator-driven (ingest revision -> rate -> bill_account routes to the adjustment path). Next action: TAR-009.

Reopened 2026-10-25 by the [independent M2 review](evidence/m2/m2-independent-review.md). Prior evidence remains historical.

Remediated 2026-10-25 (R2/R4): corrections share the same locked-revalidation boundary and sealed-journal enforcement as first issuance — adjustment journals seal with their creating transaction and revised inputs are re-validated under locks before posting. Review probes and the full suite pass.

<a id="tar-009"></a>

## TAR-009 — Deliver the core operator journey

- Repository: taryx
- Area: portal
- Milestone: M2
- Priority: High
- Status: Done ✅
- Depends on: TAR-008
- References: [Contract](features/operator-and-clients.md)

### Outcome

Expose real ingestion, bill explanation and correction workflows in GraphQL and the portal.

### Done when

- Freeze bounded query/mutation/error and operation polling contracts, auth/session approach and access controls.
- Viewer/operator/approver server-side permission checks and audit entries pass negative tests.
- Browser import/bill/explain/correct/reload journey handles unknown outcomes and uses stable operation IDs.
- M2 exit review maps correctness and integration evidence to every criterion.

### Completion evidence

Contract frozen in [decision 004](decisions/004-operator-journey-contract.md): session auth + CSRF, viewer/operator/approver groups, bounded queries, payload-code mutations, operation polling on the durable operation ID. Implemented: full GraphQL schema (bounded queries, login/logout/ingest/rate/bill/resolve mutations with server-side group checks), audit app writing entries for consequential actions, approver quarantine resolution publishing the selected candidate, seeded dev identities via seed_demo, and the React portal journey (login, ingest, rate, bill/correct with operation polling, invoice/journal/adjustment display, quarantine review). 7 tests in tests/test_graphql.py cover auth negatives per role, the complete journey ending in a linked adjustment, idempotent retry, audit assertions and stable rejection codes. make check green (92 tests). Live verification: CSRF rotation enforced, viewer denied mutation, operator bill -> polled COMPLETE outcome via the real worker. [M2 exit review](evidence/m2/m2-exit-review.md) maps evidence to all five criteria — M2 complete.

### Notes

GraphQL depth/cost bounds are not enforced beyond bounded lists (documented limitation). Browser journey verified through GraphQL contract tests and a live curl session; no browser-automation harness yet. Next action: TAR-013 (M4).

Reopened 2026-10-25 by the [independent M2 review](evidence/m2/m2-independent-review.md). Prior evidence remains historical.

Remediated 2026-10-25 (R1/R6/R7): DJANGO_CSRF_TRUSTED_ORIGINS covers the dev portal origin; the portal bootstraps CSRF with a safe GET, re-bootstraps and retries once on 403, and surfaces non-JSON/HTTP failures; billAccount resolves an existing operation by key before run selection; operation IDs are crypto.randomUUID persisted to localStorage before submission so retries after a lost response and post-reload polling resume the same identity, scoped to account+period, with terminal states clearing the intent. enforce_csrf_checks tests cover origin rejection, GET bootstrap and login rotation; vitest covers store persistence/scoping. Live browser-equivalent path verified through the Vite proxy (403 -> bootstrap -> login -> rotation -> bill -> polled COMPLETE -> identical retry resolves original).

Independent re-review of `de0e08d`: reopened for remaining R7 findings; see [review](evidence/m2/m2-independent-review.md). Original checks pass; account-switch display leakage and pending-intent overwrite reproduced.

Re-remediated 2026-10-25: AccountPanel is keyed by account.reference so switching remounts — all account-scoped state resets and the old poll interval is destroyed; operationStore keys intents per account+period and clearPending only removes the matching operationId, so an uncertain operation on one account survives billing another and delayed callbacks can't erase unrelated identities (vitest 6/6). npm test is now part of make check.

Reopened 2026-11-08 by the [foundation re-review](evidence/m1/m1-independent-review.md) of `c88b722f30526d8c57aef7ff89634ecd8a1fa983` (user-labelled M1; canonical M2). F3: issued-document UI lacks line-item provenance/explanation. Next: implement the pinned invoice explanation view and verify the operator journey.

Remediated 2026-11-08 (F3): `InvoiceType` exposes `calculationSource` and the pinned `ratingRun` (lines, digest, engine/policy identity); the portal's issued documents expand into per-line provenance — tariff, segment, quantity × rate = amount, gst and basis. tests/test_graphql.py verifies the pinned run survives subsequent re-rating.

Round-two independent review of `c270a322` (2026-11-08): F3 remains open for legacy invoices: the expander renders new-engine lines that do not reconcile to authoritative legacy totals. Render pinned authoritative evidence and distinguish comparison lines. [Review and failing follow-up probes](evidence/m1/m1-independent-review.md). Required checks pass (151 backend/6 frontend); 20 preserved probes pass and two follow-ups fail.

Re-remediated 2026-11-08 (round-2 F3): the invoice pins its authoritative calculation — `legacy_calculation_id` records the persisted shadow-alias LegacyCalculation used at issuance (billing 0009). `invoice.ratingRun` resolves per `calculationSource`: the real RatingRun for new-source bills, the pinned legacy response's own line items for legacy bills (an explicitly labelled aggregate line reconciling to net+gst when no response was pinned). RatingRun/RatingLine are now attribute-compatible ObjectTypes so both shapes serve one contract; the follow-up probe is folded into tests/test_graphql.py.

Round-three independent review at `e809640` (2026-11-08): F3: real persisted legacy lines fail with a segment-key mismatch; fix the resolver against the stored format. Verify against the real persistence path and F4-protected authoritative evidence. [Review/probes](evidence/m1/m1-independent-review.md): required checks pass, 22 preserved probes pass, two new probes fail.

Independent round-four confirmation (2026-11-08) at `2704f119`: **approved** for this foundation slice. Pinned authoritative explanation verified for new and legacy invoices, including the real simulator/persistence path; portal source and API journey tests reviewed. No fresh interactive browser session claimed. Required checks and all 25 preserved probes pass; see [review](evidence/m1/m1-independent-review.md) for scope and remaining operational verification gaps.

<a id="tar-010"></a>

## TAR-010 — Build independent legacy characterisation

- Repository: taryx
- Area: migration
- Milestone: M3
- Priority: High
- Status: Done ✅
- Depends on: TAR-009
- References: [Contract](features/legacy-migration.md)

### Outcome

Provide a standalone legacy calculator with an independent schema and reproducible historical behaviour.

### Done when

- Versioned protocol maps the same immutable snapshot to both engines.
- One fictional historical commitment and one seeded arithmetic defect have independent characterisation fixtures.
- Legacy timeout, malformed response and restart behaviour are inspectable; legacy never issues core financial records.

### Completion evidence

Implemented 2026-10-25. `legacy-sim/` is a separate image (stdlib HTTP, own sqlite calc-log schema, no core code or database credentials) serving protocol `taryx-legacy/1`. `taryx.core.migration.legacy_adapter` maps a stored `RatingRun.input_snapshot` to the versioned request — tariff specs deliberately omitted so the legacy engine resolves its own catalogue `L-2003.4`; snapshot rows gained the NEM12 trading date since interval 48's end timestamp cannot derive it (also improving snapshot reconstructibility). Scenarios: heritage `T-FLAT-FIT-HERITAGE` (legacy honours pre-GST exemption; new catalogue prices it normally) and seeded defect FIT-TRUNC-2003 (export quantity truncated to whole kWh per line). Fault injection covers timeout/malformed/unavailable/wrong_protocol; a stable failure taxonomy marks all as inconclusive. tests/test_legacy_characterisation.py: 10 subprocess-driven tests record observed behaviour independently per defect, verify restart clears faults while the sqlite log persists, and verify restart/retry preserves comparison identity by snapshot hash. Verified live in Compose (api → http://legacy:8090).

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

Reopened by independent review of `c06e1fc` (2026-10-25); all eight findings remediated and the eight preserved probes now pass as permanent regressions in tests/test_migration.py — see the [remediation addendum](evidence/m3/m3-independent-review.md#remediation-addendum--2026-10-25).

Independent re-review of `f9f21df` found F1–F4; all remediated with the five follow-up probes passing as permanent regressions — see the [second remediation addendum](evidence/m3/m3-independent-review.md#second-remediation-addendum--2026-10-25).

Re-review at `db18588`: TAR-010 remediation verified by all original adapter and invalid-response probes plus the full suite. Remaining F2 cutover serialization belongs to TAR-011/TAR-012.

2026-11-08 fresh independent re-review at `7d6c633285d98ed7afd0ed42c8c873a55c4f9faf`: reopened for M3-RR-F1/F2 (missing legacy output and malformed line identities); remediated same day — strict per-field line validation and import-usage completeness reconciliation now route both defect classes through `malformed` → INCONCLUSIVE evidence / terminal FAILED operation. All three probes folded into `tests/`; [findings and remediation](evidence/m3/m3-re-review.md).

2026-11-08 resumed independent review: **approved** at `64ace7dda5a44ddede4a91f74d54eb85e03bfbe8`. M3-RR-F1/F2 and all round-two boundary gaps resolved; 25 preserved M3 probes and full checks pass (197 backend/6 frontend). Completion confirmed within the retained browser/deployment verification limits. [Resumed evidence](evidence/m3/m3-re-review.md#round-two-resumed-independent-verification).

<a id="tar-011"></a>

## TAR-011 — Implement isolated shadow comparison and gates

- Repository: taryx
- Area: migration
- Milestone: M3
- Priority: High
- Status: Done ✅
- Depends on: TAR-010
- References: [Contract](features/legacy-migration.md)

### Outcome

Persist detailed comparison evidence with scoped discrepancy decisions and cutover eligibility.

### Done when

- Financial writes from shadow credentials/path are rejected by exercised enforcement boundaries.
- Compare item identities/quantities/rates/rounding and detect offsetting differences; missing outputs are inconclusive.
- Freeze evaluation set/freshness rules and version-scoped approval invalidation.
- Stale evidence and concurrent/in-flight routing changes cannot enable unsafe cutover.

### Completion evidence

Implemented 2026-10-25. `taryx.core.migration` holds Cohort (routing mode + optimistic revision), LegacyCalculation (verbatim response, unique per snapshot+versions), ComparisonRun (per-snapshot itemised evidence), DiscrepancyDecision (fingerprint+version-scoped approvals) and CohortEvent. The `shadow` DB alias maps to role `taryx_shadow` (migration 0001): SELECT everywhere, writes only on the two evidence tables, financial/evidence-of-record writes REVOKEd — exercised in tests via actual denied INSERT/DELETE plus allowed evidence writes. `comparison.diff_lines` pairs lines by identity and reports quantity/rate/amount/gst and totals diffs; offsetting differences still report DIFFERENCE; timeout/malformed/unavailable persist INCONCLUSIVE rows that block gates. `evaluation_blockers` freezes the rules: evidence must postdate eval_frozen_at, pin the current input digest and engine/policy versions, be conclusive, and every diff fingerprint needs a still-valid decision. `transition_cohort` enforces optimistic revision, rejects in-flight member billing ops, restricts mode edges, gates NEW_ONLY on the frozen evaluation, and audits every transition. tests/test_migration.py: 11 tests. Live: real ACC-001 comparison detected the FIT-TRUNC defect (quantity 9.6→9) with itemised diffs; gate reported unresolved differences and missing ACC-003 evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

Reopened by independent review of `c06e1fc` (2026-10-25); all eight findings remediated and the eight preserved probes now pass as permanent regressions in tests/test_migration.py — see the [remediation addendum](evidence/m3/m3-independent-review.md#remediation-addendum--2026-10-25).

Independent re-review of `f9f21df` found F1–F4; all remediated with the five follow-up probes passing as permanent regressions — see the [second remediation addendum](evidence/m3/m3-independent-review.md#second-remediation-addendum--2026-10-25).

Re-review of `db18588` reopened this task for the remaining F2 commit-window race; remediated with the cohort advisory-lock protocol — the commit-window probe now passes as a permanent regression. See the [third remediation addendum](evidence/m3/m3-independent-review.md#third-remediation-addendum--2026-10-25).

2026-11-08 fresh independent re-review at `7d6c633285d98ed7afd0ed42c8c873a55c4f9faf`: reopened for M3-RR-F1/F2 (missing legacy output and malformed line identities); remediated same day — strict per-field line validation and import-usage completeness reconciliation now route both defect classes through `malformed` → INCONCLUSIVE evidence / terminal FAILED operation. All three probes folded into `tests/`; [findings and remediation](evidence/m3/m3-re-review.md).

2026-11-08 resumed independent review: **approved** at `64ace7dda5a44ddede4a91f74d54eb85e03bfbe8`. M3-RR-F1/F2 and all round-two boundary gaps resolved; 25 preserved M3 probes and full checks pass (197 backend/6 frontend). Completion confirmed within the retained browser/deployment verification limits. [Resumed evidence](evidence/m3/m3-re-review.md#round-two-resumed-independent-verification).

<a id="tar-012"></a>

## TAR-012 — Deliver operator migration and cutover

- Repository: taryx
- Area: portal
- Milestone: M3
- Priority: High
- Status: Done ✅
- Depends on: TAR-011
- References: [Contract](features/legacy-migration.md)

### Outcome

Let an authorised operator investigate and migrate cohorts with auditable evidence.

### Done when

- Portal explains both differences and records preserve-policy or approved-defect decisions with reasons/versions.
- Legacy/shadow/new transitions and future-routing rollback obey server-side guards and permissions.
- Browser/process evidence covers stale screens, in-flight issuance and inconclusive results; M3 exit review passes.

### Completion evidence

Implemented 2026-10-25. Billing ops pin `cohort_mode`/`cohort_revision` at admission; `process_operation` revalidates routing under `lock_inputs` (stale_routing raised on mismatch) and derives invoice amounts via the injected `calculate_for_billing` — legacy-authoritative under LEGACY_ONLY and SHADOW, with SHADOW persisting the comparison inline. Invoice.calculation_source records the engine. GraphQL: cohorts/comparisons/cohortEvents queries, decideDiscrepancy (operator+approver) and transitionCohort (approver) mutations with payload codes; viewer denied. Portal MigrationPanel renders mode/revision, eval window, gate blockers, per-account status and itemised diffs, records decisions and drives guarded transitions. Live: stale_revision rejection, SHADOW bill produced INV-000002 at legacy total 7.27 (new: 8.05), 9 scoped decisions, in_flight blocked rollback until drained, cutover gated, rollback to LEGACY_ONLY, full cohortEvents audit; injected malformed fault produced INCONCLUSIVE + gate blocker. 17 new tests; 131 total green. See evidence/m3/m3-exit-review.md.

### Notes

Rollback concerns future routing only; issued bills are never reversed. Residuals recorded in evidence/m3/m3-exit-review.md.

Reopened by independent review of `c06e1fc` (2026-10-25); all eight findings remediated and the eight preserved probes now pass as permanent regressions in tests/test_migration.py — see the [remediation addendum](evidence/m3/m3-independent-review.md#remediation-addendum--2026-10-25).

Independent re-review of `f9f21df` found F1–F4; all remediated with the five follow-up probes passing as permanent regressions — see the [second remediation addendum](evidence/m3/m3-independent-review.md#second-remediation-addendum--2026-10-25).

Re-review of `db18588` reopened this task for the remaining F2 commit-window race; remediated with the cohort advisory-lock protocol — the commit-window probe now passes as a permanent regression. See the [third remediation addendum](evidence/m3/m3-independent-review.md#third-remediation-addendum--2026-10-25).

2026-11-08 fresh independent re-review at `7d6c633285d98ed7afd0ed42c8c873a55c4f9faf`: reopened for M3-RR-F1/F2 (missing legacy output and malformed line identities); remediated same day — strict per-field line validation and import-usage completeness reconciliation now route both defect classes through `malformed` → INCONCLUSIVE evidence / terminal FAILED operation. All three probes folded into `tests/`; [findings and remediation](evidence/m3/m3-re-review.md).

2026-11-08 resumed independent review: **approved** at `64ace7dda5a44ddede4a91f74d54eb85e03bfbe8`. M3-RR-F1/F2 and all round-two boundary gaps resolved; 25 preserved M3 probes and full checks pass (197 backend/6 frontend). Completion confirmed within the retained browser/deployment verification limits. [Resumed evidence](evidence/m3/m3-re-review.md#round-two-resumed-independent-verification).

<a id="tar-013"></a>

## TAR-013 — Demonstrate two isolated client instances

- Repository: taryx
- Area: deployment
- Milestone: M4
- Priority: High
- Status: Done ✅
- Depends on: TAR-012
- References: [Contract](features/operator-and-clients.md)

### Outcome

Run two fictional retailers from one core image with independent state and policy.

### Done when

- Same image digest, separate credentials/databases/vhosts and distinct policy outputs are demonstrated.
- Cross-client IDs, credentials and message routes cannot access the other client.
- Import contracts enforce client independence; shared physical infrastructure limits are documented.

### Completion evidence

Round 5 at `98fad76`: approved remediation; live same-image and imported account/market code freshness verified in all four app containers. TAR-013 closed. [Evidence](evidence/m4/m4-review-r5.md).

Authorised round 4 at `853842c9ba24c92aa7d487ca3546910eef7107e1`: F11 same-image discrepancy resolved by live inspection; preserved isolation probes pass. Runtime market code differs from the candidate, so deployment verification remains qualified and this task stays In progress pending candidate-image verification. [Review](evidence/m4/m4-review-r4.md).

2026-11-08 independent round 3 at `4b65cf589537fbbfba449e5e82b80ccb5597c354`: **changes requested** — M4-F9 isolation verified resolved, but new M4-F11 fails the same-image-digest criterion. Original probes 22 pass; expanded probes 22 pass/5 fail; project checks pass (216 backend/6 frontend). [Round-3 findings](evidence/m4/m4-independent-review.md#round-3--independent-verification-2026-11-08) supersede remediation completion claims below. Remediate and escalate to the user at the three-round cap before another review round.

2026-11-08 R3 remediation: M4-F11 resolved — all four app services reference one named image `taryx-app:latest` built once on `api`; live `docker inspect` confirms a shared digest across `api`/`api-sg`/`worker`/`worker-sg`. Also transferred object ownership to `taryx_app` so the demoted role can still run `ALTER TABLE` migrations. `make check` green (221 backend/6 frontend). Pending independent re-review.

2026-11-08 R2 remediation: M4-F9 resolved — per-client shadow credentials (`taryx_shadow_sg` for southgrid; shared `taryx_shadow` denied CONNECT and object privileges on `taryx_southgrid` via migration `0005` resolving the per-database `taryx.shadow_role` GUC). Live isolation probes confirm denial in both directions; `make check` green (216 backend/6 frontend). Pending independent re-review.

2026-11-08 independent round 2 at `d18312195a4facb3480720854e9f0a863974603b`: **changes requested** for new M4-F9 shared shadow credential bypass. Reopened pending remediation and re-review. Original ten probes pass; expanded probes 12 pass/10 fail; project checks pass (205 backend/6 frontend). [Round-2 review](evidence/m4/m4-independent-review.md#round-2--independent-verification-2026-11-08) supersedes the remediation completion claims below.

2026-11-08 R1 remediation: M4-F1–F3 resolved — `taryx_app` is no longer a member of the `taryx` superuser (SET ROLE denied outright; direct owner-equivalent grants on aurora objects); application broker users are non-administrator accounts (`taryx_admin` confined to `broker-init`); per-client market/callback tokens on both adapters and simulators. All 3 live isolation probes pass; `make check` green (205 backend/6 frontend). Pending independent re-review. [Remediation detail](evidence/m4/m4-independent-review.md#remediation--round-1-2026-11-08)

2026-11-08 independent M4 review at `2dbc5b0`: **changes requested**; reopened for M4-F1–F3 (effective credential isolation). [Review and runnable probes](evidence/m4/m4-independent-review.md). Prior implementation evidence below is historical; remediate findings and rerun independent review before completion.

Live two-client deployment verified on 2026-11-08 (both stacks running from `build: .` — same image and compose file):

- Database: `taryx_app`/`taryx` (aurora) vs `taryx_sg`/`taryx_southgrid` (southgrid); CONNECT refused in both directions (`taryx_app→taryx_southgrid`, `taryx_sg→taryx`), `taryx_shadow` reaches both for per-database evidence grants. Aurora app runs as non-superuser `taryx_app` (member of the bootstrap owner); the superuser stays confined to `db-init` provisioning.
- Broker: vhost `taryx` for user `taryx`, vhost `taryx-sg` for `taryx_sg`; AMQP connect refused in both directions (creator's auto-grant revoked by `broker/init/provision.py`, HTTP management API, idempotent).
- Services: `api-sg` (8002), `worker-sg`, `legacy-sg` (18091, own volume) and `web-sg` (5175) up alongside aurora's; `worker-sg` consumed on `taryx-sg`.
- Divergent policy output: ACC-001 2026-03-02 rated net 8.64/gst 0.95/total 9.59 under southgrid vs the same-day aurora invoice at 8.75 on identical inputs; distinct `policy_identity` and digest.
- Overlapping identifiers: southgrid ACC-001..003 are distinct businesses ("Bayview Corner Store" vs "Meridian Heights Bakery") under the same references and NMIs — seeded per deployment via `seed_client`.
- Tests: `tests/test_clients.py` (4) + `tests/test_deployment_isolation.py` (5, declaration checks); `make check` green — 178 backend, 6 frontend, lint/format, mypy, import contracts (3 kept; the reported core→interfaces "violation" is the deliberate negative probe), build.

Limits: shared physical Postgres server and broker — per the contract this demonstrates credentials/data/route isolation, not independent fault domains. `docker compose` service identity, not a digest-pinning registry flow, is the same-image evidence.

### Notes

2026-11-08: client policy packages implemented — `taryx.clients.aurora_energy` re-exports the au_nem baseline; `taryx.clients.southgrid_retail` carries same-code/different-value tariffs, its own catalogue identity and demo specs with deliberately overlapping account references/NMIs. `taryx.composition.policy` resolves `TARYX_CLIENT` once at startup (default aurora, unknown client fails fast) and injects tariffs/GST/policy identity into tasks, GraphQL and management commands. `seed_client` command seeds client-specific specs. Import-linter already enforces client independence and layering. Remaining: second compose instance with separate DB/role and broker vhost, plus cross-client negative evidence. tests/test_clients.py: 4 tests.


## TAR-014 — Freeze the bounded market workflow

- Repository: taryx
- Area: integration
- Milestone: M4
- Priority: Normal
- Status: Done ✅
- Depends on: TAR-012
- References: [Contract](features/market-integration.md), [Decision 005](decisions/005-market-workflow-contract.md)

### Outcome

Resolve BLK-002 into a reviewable transition/protocol contract.

### Done when

- Select one scenario and source any real market claims; clearly label synthetic transport and timing.
- Specify versioned request/response/events, identity/authentication, state transitions, deduplication, deadlines and reconciliation.
- Define deterministic fault scripts and independent expected terminal states.

### Completion evidence

Frozen 2026-11-08 in [decision 005](decisions/005-market-workflow-contract.md): synthetic `taryx-market/1` JSON/HTTP protocol (explicitly not an AEMO/MSATS claim), one scenario (supply-point transfer request, adapter → coordinator), versioned request/ack/callback/poll shapes, bearer-token + version-header ingress, `draft → submitted → (completed|rejected)` with `reconciling`/`failed` failure states, a frozen transition table covering duplicate/late/out-of-order/unknown-correlation/malformed events, inbox/outbox dedup rules, deadline + bounded-retry + reconciliation semantics, restart recovery, and nine deterministic simulator fault scripts. BLK-002 resolved.

### Notes

Contract-only task — no runtime code yet; TAR-015 implements the coordinator simulator and adapter against this table. Amendments to the transition table go through the decision record first.

<a id="tar-015"></a>

## TAR-015 — Implement market adapter and counterparty simulator

- Repository: taryx
- Area: integration
- Milestone: M4
- Priority: Normal
- Status: Done ✅
- Depends on: TAR-013, TAR-014
- References: [Contract](features/market-integration.md), [Decision 005](decisions/005-market-workflow-contract.md)

### Outcome

Complete one durable market workflow across owned adapter and external test double.

### Done when

- Independent adapter database/inbox/outbox and core contract enforce service ownership.
- Delay/duplicate/reorder/reject/timeout/restart cases follow the frozen profile without duplicate transitions.
- Uncertain outcomes reconcile; unrelated core work stays responsive; M4 exit evidence is recorded.

### Completion evidence

2026-11-13: the two remaining exit-evidence items are satisfied by the TAR-016 fault campaign — `market-adapter-restart` (worker killed between the durable attempt marker and the counterparty POST; `draft:1` recovered to `completed` by the restarted worker's poll-first sweep) and `billing-under-market-outage` (billing op completed while the market coordinator was stopped). [Evidence](evidence/m5/fault-campaign.md). All Done-when items now have evidence.

Round 5 at `98fad76`: **approved** remediation; M4-F8 resolved, 28 preserved/31 expanded probes pass and live imported modules match. Remains In progress for explicit market-outage billing availability and live adapter-restart exit evidence (or accepted allocation to TAR-016). No new code finding. [Review](evidence/m4/m4-review-r5.md).

Authorised round 4 at `853842c9ba24c92aa7d487ca3546910eef7107e1`: F7/F10 reported cases resolved; F8 remains open: a consumer using a stale supply-point instance can register a newer pending transfer. Keep In progress; make correlation validation/update atomic and retain the new interleaving probe. [Review](evidence/m4/m4-review-r4.md).

2026-11-08 independent round 3 at `4b65cf589537fbbfba449e5e82b80ccb5597c354`: **changes requested** — M4-F5 crash recovery verified resolved; M4-F7/F8 remain and new M4-F10 affects the submission budget. Original probes 22 pass; expanded probes 22 pass/5 fail; project checks pass (216 backend/6 frontend). [Round-3 findings](evidence/m4/m4-independent-review.md#round-3--independent-verification-2026-11-08) supersede remediation completion claims below. Remediate and escalate to the user at the three-round cap before another review round.

2026-11-08 R3 remediation: M4-F7 (boolean `last_seq` rejected instead of aborting the sweep), M4-F8 (`SupplyPoint.pending_transfer_id` migration 0003 — the core consumer dedups per correlation so a stale outbox replay cannot re-register a point with a newer pending transfer), and M4-F10 (attempt markers count POSTs: `MARKET_MAX_ATTEMPTS=1` allows the initial submit; five transport failures end `failed`) all resolved. Probes folded into `tests/test_market.py`; `make check` green (221 backend/6 frontend). Pending independent re-review.

2026-11-08 R4 remediation: M4-F8 closed — the consumer's correlation check is now a single conditional `UPDATE` evaluated against current database state (stale-instance read can no longer register a newer pending transfer); `clear_pending_transfer`/`begin_transfer` use the same atomic pattern. Probe rewritten and folded into `tests/test_market.py`; `make check` green (222 backend/6 frontend); live image rebuilt so running code matches the candidate. Pending independent re-review.

2026-11-08 R2 remediation: M4-F5/F7/F8 resolved — durable pre-network attempt marker survives crash rollback so resends always poll; reconcile requires matching `correlation_id` and transport rejects non-object JSON; the drain validates the full envelope and a distinct core consumer (`taryx.core.accounts.services`) owns all supply-point market-state mutations. Round-2 probes folded into `tests/test_market.py`/`test_deployment_isolation.py`; `make check` green. Pending independent re-review.

2026-11-08 independent round 2 at `d18312195a4facb3480720854e9f0a863974603b`: **changes requested** for remaining M4-F5/F7/F8 crash recovery and protocol/core validation. Reopened pending remediation and re-review. Original ten probes pass; expanded probes 12 pass/10 fail; project checks pass (205 backend/6 frontend). [Round-2 review](evidence/m4/m4-independent-review.md#round-2--independent-verification-2026-11-08) supersedes the remediation completion claims below.

2026-11-08 R1 remediation: M4-F4–F8 resolved — HTTP-failure submits exhaust to `failed`; uncertain resends poll `GET /transfers/{correlation_id}` first; the expiry→`reconciling` move is a state-guarded update; callback/ack/reconcile fields and correlations are strictly validated; the outbox drain validates the versioned `market.transfer_completed` envelope before mutating core. 7/7 service probes pass and are folded into `tests/test_market.py` (`TestReviewProbes`); `make check` green. Pending independent re-review. [Remediation detail](evidence/m4/m4-independent-review.md#remediation--round-1-2026-11-08)

2026-11-08 independent M4 review at `2dbc5b0`: **changes requested**; reopened for M4-F4–F8 (recovery, transitions and protocol/core validation). [Review and runnable probes](evidence/m4/m4-independent-review.md). Prior implementation evidence below is historical; remediate findings and rerun independent review before completion.

Implemented and verified 2026-11-08 against the decision-005 frozen contract:

- `market-sim/` — independent coordinator subprocess/container (stdlib HTTP + own sqlite), no shared code with core. Idempotent `/transfers` (correlation dedup, 409 on digest conflict), `GET /transfers/{id}` reconcile poll, nine deterministic scenario scripts and fault modes via `/_admin/*`.
- `taryx.core.market` — `TransferWorkflow` (durable draft→submitted→reconciling→terminal, attempts, deadlines, last counterparty status), `MarketInbox` ((correlation_id, seq) dedup with applied/duplicate/late notes), `MarketException` (unknown-correlation/malformed parking), `MarketOutbox` (transactional delivery → `supply_point.market_state=registered`). The adapter never writes billing/account tables outside the outbox consumer path.
- Ingress `POST /callbacks/transfers` — bearer token + version header before any state; malformed bodies parked and 400'd. Celery tasks `market.submit`, `market.sweep` (retry/deadline/reconcile), `market.drain`; beat schedule drives sweep+drain every 10s. GraphQL `requestTransfer` mutation (operator role) and `marketWorkflow(s)`/`marketExceptions` queries.
- Deployment: `market`/`market-sg` services per client with own volumes; both workers run embedded beat.
- Live E2E on aurora: `requestTransfer(4102000001)` → submitted → happy callback → completed → drain → `market_state: registered`; a discarded submit task was recovered by the sweep (lost-submit path exercised live).
- tests/test_market.py — 19 tests: full transition table (happy, duplicate, late/lower-seq, reject, unknown correlation, malformed, lost-response→failed, reconcile-resolves, budget exhaustion, retry exhaustion, 409), real-sim subprocess (idempotent resubmit, 409, HTTP callback, auth/version rejection, four scenario delivery patterns), endpoint auth/malformed.
- `make check` green — 197 backend, 6 frontend, lint/format, mypy, import contracts (3 kept; deliberate probe rejected), build; `docker compose config` valid.

Limits: scenarios are deterministic scripts, not real market timing; `callback_url` in submit is simulator plumbing (decision record updated); single-beat-per-worker scheduling is the local driver, not a clustered scheduler.

### Notes

The adapter's market outbox is separate from `billing.OutboxEvent` (operation-linked) — a deliberate parallel mechanism for non-billing events.

<a id="tar-016"></a>

## TAR-016 — Verify recovery and correlated diagnostics

- Repository: taryx
- Area: verification
- Milestone: M5
- Priority: Normal
- Status: Done ✅
- Depends on: TAR-015
- References: [Contract](features/verification.md)

### Outcome

Complete real-process fault evidence and actionable operational visibility.

### Done when

- Exercise SIGKILL before/after financial commit, broker outage, duplicate delivery and abandoned-lease recovery.
- Metrics/logs/traces identify operations across queues/services with bounded labels and redacted payloads.
- Sentry capture path is tested locally or hosted with limitations recorded; no external account required for the default demo.
- Frozen recovery and API-responsiveness budgets pass under the declared workload.

### Completion evidence

2026-11-13 diagnostics slice: structured JSON logs with bounded labels (`request_id`/`task_id`/`operation_id`/`correlation_id` bound via contextvars; celery signal task binding; `X-Request-ID` middleware; redaction inside the formatter), `/metrics` Prometheus counters on enum statuses only, `sentry-sdk==2.74.0` with `SENTRY_DSN`-gated init and a local in-process-transport capture test (no external account). 9 tests + live verification on compose. [Evidence](evidence/m5/diagnostics.md). Fault campaign and budget runs still open.

2026-11-13 fault campaign: `scripts/fault-campaign.py` drives seven real-container scenarios — `docker kill --signal=KILL` on the worker at code-level fault points (`TARYX_BILLING_PRECOMMIT_SLEEP`/`TARYX_BILLING_POSTCOMMIT_SLEEP`/`TARYX_MARKET_SUBMIT_SLEEP`), broker and market `compose stop` outages, duplicate task dispatch and an abandoned consumer lease. All seven pass: zero financial effect before commit, exactly one after commit+kill and after duplicate delivery, durable outbox admission with the API responsive during broker outage, queued intent surviving a missing consumer, the market adapter restart recovering a `draft:1` workflow to `completed` via poll-first resend, and billing completing with the market coordinator down. [Evidence](evidence/m5/fault-campaign.md) + machine-readable [jsonl](evidence/m5/fault-campaign.jsonl). The two TAR-015 exit-evidence items (live adapter restart, billing-under-market-outage) are satisfied by this campaign.

2026-11-13 budget runs: `scripts/measure-budgets.py` seeds 100 R1 accounts and ingests the frozen R1 workload (180k intervals) while probing `/healthz` (`SELECT 1`) and `/metrics` (status aggregations), then times a real SIGKILL recovery. Results: R1 ingest **32.9 s** (budget ≤ 90 s), API read p95 **23.1 ms healthz / 34.7 ms metrics** during ingestion (budget ≤ 500 ms), kill-to-complete **6.8 s** with exactly one invoice (budget ≤ 60 s). [Evidence](evidence/m5/budget-runs.md) + [jsonl](evidence/m5/budget-runs.jsonl). The first R1 attempt exposed a real defect: `_apply_selection` issued ~5 queries per interval (~1M for R1) and was killed uncommitted after 20+ min; it now runs the two-phase protocol at bulk granularity (one account lock per account, per-channel candidate/current fetches, in-memory winner evaluation, `ignore_conflicts` bulk create, strict per-interval fallback for lost create-races, bulk quarantine resolution). All Done-when items now have evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-017"></a>

## TAR-017 — Package and verify Kubernetes delivery

- Repository: taryx
- Area: deployment
- Milestone: M5
- Priority: Normal
- Status: Done ✅
- Depends on: TAR-016
- References: [Contract](architecture.md)

### Outcome

Reproduce the application on kind with controlled rollouts and worker lifecycle.

### Done when

- Fresh-cluster manifests/chart start isolated clients and services with explicit persistent storage/reset boundaries.
- Migration Job precedes compatible workload rollout; failed migration/readiness prevents unsafe advancement.
- Graceful termination and forced worker kill preserve correctness; queue-based scaling has bounded measured behaviour.
- Network/credential boundaries and resource limits are exercised, not just configured.

### Completion evidence

2026-11-13 kind delivery: `deploy/k8s/manifests/` + `install.sh`/`reset.sh` bring up the full two-client stack on a fresh cluster — db/broker StatefulSets on PVCs, per-client Jobs (`db-init`, `broker-provision`, `migrate-aurora`, `migrate-southgrid`), api/worker pods per client on one image, sims on `emptyDir`. The `wait-migrated` initContainer held all four app pods in `Init` until each client's migration Job completed — failed or pending migrations cannot be outrun. Exercised: unlabeled pod blocked from db/broker by NetworkPolicy while `api:8000` stayed open; cross-client `psql` denied both directions; `--grace-period=0` pod kill left the op `pending` with zero effect and drain produced exactly one invoice; graceful delete let warm shutdown finish the in-flight task; `worker` at 2 replicas with duplicate deliveries produced one invoice per operation with the queue drained to 0; `reset.sh` wiped PVCs and reinstalled to seed-only state. [Evidence](evidence/m5/kubernetes.md), [README](deploy/k8s/README.md).

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-018"></a>

## TAR-018 — Measure and present the portfolio release

- Repository: taryx
- Area: verification
- Milestone: M5
- Priority: Normal
- Status: Backlog 📋
- Depends on: TAR-017
- References: [Contract](features/verification.md)

### Outcome

Deliver a reproducible complete demo with measured evidence and honest limitations.

### Done when

- Run the required workload/repetition profile and report resource/latency/throughput results against frozen budgets.
- Clean setup/reset and full billing/correction/migration/client/market journey are reproduced; recording and concise walkthrough are provided.
- Audit verification matrix, open gates, milestone exits and document links; unresolved required checks keep M5 open.
- README setup is verified; hosted CI/cloud/live-market claims are explicitly distinguished from local results.

### Completion evidence

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-019"></a>

## TAR-019 — Evaluate the multi-agent implement/review orchestrator

- Repository: taryx
- Area: workspace
- Milestone: Not assigned
- Priority: Low
- Status: In progress 🚧
- Depends on: None
- References: [Problem framing](../agent-notes/multi-agent-handoff-problem.md), [Orchestrator research](../agent-notes/multi-agent-orchestrator-research.md)

### Outcome

Decide the architecture for the autonomous Devin–Codex implement/review
loop (thin orchestrator, MCP inversion, or hybrid) and prototype the
chosen mechanism on one milestone.

### Done when

- Devin-side headless invocation is verified (install `devin` CLI, or
  record why the MCP/hybrid route was chosen).
- `codex exec --output-schema` verdict contract verified empirically.
- A bounded review loop runs end-to-end on one milestone with all pushes
  still manual.

### Completion evidence

Pending.

### Notes

Simplified approach chosen 2026-11-08: Devin drives the loop in-session
via `codex exec resume` against the existing review thread — see
docs/agent-notes/codex-review-loop.md. `codex exec` smoke-tested;
`codex exec resume` reaches the thread but conflicts on the app
writer-lock while the thread is open. M3 dry-run (4 rounds) showed the
thread's managed restricted profile is read-only with an unrelated
cwd — findings arrive via `-o` (saved as .md) but Codex cannot write
docs or run DB tests. Resolved design 2026-11-08: dedicated `codex exec`
session as the review thread — created with `--approve-for-me` +
network access; resume inherits workspace-write (writes verified on
create and resume). Remaining: one full write-capable review round
end-to-end, including DB access.

Audit follow-up (2026-11-08): [CLI/process audit](../agent-notes/codex-review-loop-audit.md) distinguishes writable sandbox access from retained automatic approvals. Existing `/tmp` probes do not establish repository writes or DB access. CLI 0.153.4 exposes schema output on resume/fork; live schema and permission behavior remain to be verified. Recommendations are not yet adopted or implemented.

Pilot doc reconciled after the audit (2026-11-08): per-milestone
sessions, git-status tree gate, schema-constrained verdict JSON
(docs/project/evidence/verdict.schema.json created), flag ordering,
and corrected permission claims. Codex's own audit run wrote into the
repo under --approve-for-me — first live repo-write evidence.
Remaining: provision the M4 review session, one full schema-verdict
round including DB access.

<a id="tar-020"></a>

## TAR-020 — Design the operator portal UI

- Repository: taryx
- Area: portal
- Milestone: Not assigned
- Priority: Normal
- Status: In progress 🚧
- Depends on: None
- References: [design demos](../design/index.html)

### Outcome

Replace the primitive black/white portal styling with an enterprise
operations-console design: high information density on desktop (flat
visibility rather than layered disclosure), dark/light/auto themes,
and a direction chosen between two static candidates.

### Done when

- User selects a direction (or a merge) between the two demo pages.
- Chosen design applied to `web/` behind the existing GraphQL contract,
  with theme switching verified in the real app.

### Completion evidence

Static demos built 2026-11-13 at `docs/design/` — `design-a-console.html`
(three-pane mission console) and `design-b-suite.html` (tabbed
master-detail suite), seeded with realistic demo data. `login.html`
added with a shared split-panel sign-in; both designs scaled to the
user-approved 120% density via CSS `zoom`. User likes both directions;
final choice pending before touching `web/src/App.tsx`.

### Notes

Both candidates share a localStorage theme key so light/dark/auto
compares identically. Density approach: ~12px base type, monospace
numerals, status chips, all rating lines and journal postings visible
without expansion.
