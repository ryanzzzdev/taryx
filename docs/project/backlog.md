# Taryx backlog

Updated: 2026-10-25

Task sections own status; index icons mirror them. See the [documentation guide](documentation-guide.md#task-records).

## Task index

- ✅ [TAR-001 — Establish project-management standards](#tar-001)
- ✅ [TAR-002 — Establish the planning baseline](#tar-002)
- 🟢 [TAR-003 — Bootstrap the development workspace](#tar-003)
- 📋 [TAR-004 — Freeze domain and measurement profiles](#tar-004)
- 📋 [TAR-005 — Implement versioned meter ingestion and fixtures](#tar-005)
- 📋 [TAR-006 — Implement deterministic itemised rating](#tar-006)
- 📋 [TAR-007 — Implement durable issuance and balanced posting](#tar-007)
- 📋 [TAR-008 — Implement successive corrections and adjustments](#tar-008)
- 📋 [TAR-009 — Deliver the core operator journey](#tar-009)
- 📋 [TAR-010 — Build independent legacy characterisation](#tar-010)
- 📋 [TAR-011 — Implement isolated shadow comparison and gates](#tar-011)
- 📋 [TAR-012 — Deliver operator migration and cutover](#tar-012)
- 📋 [TAR-013 — Demonstrate two isolated client instances](#tar-013)
- 📋 [TAR-014 — Freeze the bounded market workflow](#tar-014)
- 📋 [TAR-015 — Implement market adapter and counterparty simulator](#tar-015)
- 📋 [TAR-016 — Verify recovery and correlated diagnostics](#tar-016)
- 📋 [TAR-017 — Package and verify Kubernetes delivery](#tar-017)
- 📋 [TAR-018 — Measure and present the portfolio release](#tar-018)

## Delivery notes

Next action: TAR-003. TAR-004 source research may proceed alongside bootstrap, but its measurement acceptance depends on the running skeleton. Later tasks remain Backlog until their dependencies and detailed contracts are ready. Portal/API slices can develop alongside their backend tasks; TAR-009 and TAR-012 own integrated acceptance. Observability hooks and correctness tests accompany implementation; TAR-016 owns the full cross-service campaign, not the first tests.

The architecture and functional scope are the planning baseline; exact schemas, dependency versions and open profiles are refined in their named tasks. Split large tasks into new IDs before starting if necessary; preserve existing history. Next unused ID: TAR-019. No application work has started.

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
- Status: Ready 🟢
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

Not started; no implementation or verification evidence.

### Notes

Begin with dependency compatibility research and the smallest runnable workspace.

<a id="tar-004"></a>

## TAR-004 — Freeze domain and measurement profiles

- Repository: taryx
- Area: verification
- Milestone: M1
- Priority: High
- Status: Backlog 📋
- Depends on: TAR-003
- References: [Contract](features/metering-and-rating.md)

### Outcome

Resolve the supported meter/tariff/time profile and independent reference cases before building the engine.

### Done when

- Close BLK-001 with authoritative format references, supported record subset, revision/quality precedence, time conventions, unit/tax/rounding rules and explicit exclusions.
- Create independently calculated expected cases including time/effective-date boundaries and invalid inputs.
- Close BLK-003 with reference hardware, required workload, resource limits and latency/throughput/recovery budgets measured from the bootstrap baseline.

### Completion evidence

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-005"></a>

## TAR-005 — Implement versioned meter ingestion and fixtures

- Repository: taryx
- Area: metering
- Milestone: M1
- Priority: High
- Status: Backlog 📋
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

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-006"></a>

## TAR-006 — Implement deterministic itemised rating

- Repository: taryx
- Area: pricing
- Milestone: M2
- Priority: High
- Status: Backlog 📋
- Depends on: TAR-005
- References: [Contract](features/metering-and-rating.md)

### Outcome

Calculate supported supply/import/export charges from immutable snapshots.

### Done when

- Decimal calculations and rounding match independent reference cases.
- Agreement/tariff changes and time boundaries are explicit; gaps prevent rating/issuance.
- Output records input identities, quantities, rates, rounding and engine/policy versions; replay is deterministic.

### Completion evidence

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-007"></a>

## TAR-007 — Implement durable issuance and balanced posting

- Repository: taryx
- Area: billing
- Milestone: M2
- Priority: High
- Status: Backlog 📋
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

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-008"></a>

## TAR-008 — Implement successive corrections and adjustments

- Repository: taryx
- Area: billing
- Milestone: M2
- Priority: High
- Status: Backlog 📋
- Depends on: TAR-007
- References: [Contract](features/billing-and-ledger.md)

### Outcome

Reconcile revised liability against all previously recognised liability without changing issued records.

### Done when

- Corrected data identifies affected periods and generates traceable debit/credit or zero-delta outcomes.
- Repeated and successive revisions do not duplicate prior adjustments.
- Concurrent revisions/stale calculations and interrupted adjustment posting preserve the intended recognised generation.

### Completion evidence

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-009"></a>

## TAR-009 — Deliver the core operator journey

- Repository: taryx
- Area: portal
- Milestone: M2
- Priority: High
- Status: Backlog 📋
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

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-010"></a>

## TAR-010 — Build independent legacy characterisation

- Repository: taryx
- Area: migration
- Milestone: M3
- Priority: High
- Status: Backlog 📋
- Depends on: TAR-009
- References: [Contract](features/legacy-migration.md)

### Outcome

Provide a standalone legacy calculator with an independent schema and reproducible historical behaviour.

### Done when

- Versioned protocol maps the same immutable snapshot to both engines.
- One fictional historical commitment and one seeded arithmetic defect have independent characterisation fixtures.
- Legacy timeout, malformed response and restart behaviour are inspectable; legacy never issues core financial records.

### Completion evidence

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-011"></a>

## TAR-011 — Implement isolated shadow comparison and gates

- Repository: taryx
- Area: migration
- Milestone: M3
- Priority: High
- Status: Backlog 📋
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

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-012"></a>

## TAR-012 — Deliver operator migration and cutover

- Repository: taryx
- Area: portal
- Milestone: M3
- Priority: High
- Status: Backlog 📋
- Depends on: TAR-011
- References: [Contract](features/legacy-migration.md)

### Outcome

Let an authorised operator investigate and migrate cohorts with auditable evidence.

### Done when

- Portal explains both differences and records preserve-policy or approved-defect decisions with reasons/versions.
- Legacy/shadow/new transitions and future-routing rollback obey server-side guards and permissions.
- Browser/process evidence covers stale screens, in-flight issuance and inconclusive results; M3 exit review passes.

### Completion evidence

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-013"></a>

## TAR-013 — Demonstrate two isolated client instances

- Repository: taryx
- Area: deployment
- Milestone: M4
- Priority: Normal
- Status: Backlog 📋
- Depends on: TAR-012
- References: [Contract](features/operator-and-clients.md)

### Outcome

Run two fictional retailers from one core image with independent state and policy.

### Done when

- Same image digest, separate credentials/databases/vhosts and distinct policy outputs are demonstrated.
- Cross-client IDs, credentials and message routes cannot access the other client.
- Import contracts enforce client independence; shared physical infrastructure limits are documented.

### Completion evidence

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-014"></a>

## TAR-014 — Freeze the bounded market workflow

- Repository: taryx
- Area: integration
- Milestone: M4
- Priority: Normal
- Status: Backlog 📋
- Depends on: TAR-012
- References: [Contract](features/market-integration.md)

### Outcome

Resolve BLK-002 into a reviewable transition/protocol contract.

### Done when

- Select one scenario and source any real market claims; clearly label synthetic transport and timing.
- Specify versioned request/response/events, identity/authentication, state transitions, deduplication, deadlines and reconciliation.
- Define deterministic fault scripts and independent expected terminal states.

### Completion evidence

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-015"></a>

## TAR-015 — Implement market adapter and counterparty simulator

- Repository: taryx
- Area: integration
- Milestone: M4
- Priority: Normal
- Status: Backlog 📋
- Depends on: TAR-013, TAR-014
- References: [Contract](features/market-integration.md)

### Outcome

Complete one durable market workflow across owned adapter and external test double.

### Done when

- Independent adapter database/inbox/outbox and core contract enforce service ownership.
- Delay/duplicate/reorder/reject/timeout/restart cases follow the frozen profile without duplicate transitions.
- Uncertain outcomes reconcile; unrelated core work stays responsive; M4 exit evidence is recorded.

### Completion evidence

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-016"></a>

## TAR-016 — Verify recovery and correlated diagnostics

- Repository: taryx
- Area: verification
- Milestone: M5
- Priority: Normal
- Status: Backlog 📋
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

Not started; no implementation or verification evidence.

### Notes

Refine and mark Ready once dependencies pass; record relevant gate resolutions before dependent implementation.

<a id="tar-017"></a>

## TAR-017 — Package and verify Kubernetes delivery

- Repository: taryx
- Area: deployment
- Milestone: M5
- Priority: Normal
- Status: Backlog 📋
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

Not started; no implementation or verification evidence.

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
