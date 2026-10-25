# Taryx roadmap

Date: 2026-10-25

This is the initial delivery sequence, not a calendar commitment. The earlier 6–10 week ambition is a sizing hypothesis; reassess after M1 and M3. [Backlog](backlog.md) owns task status; [architecture](architecture.md) owns design. M1 is complete after remediation of the independent exit review findings.

| Milestone | Outcome | Status | Depends on |
| --- | --- | --- | --- |
| Documentation setup | Portable Cateniq-style workflow | Complete | None |
| Planning baseline | Architecture, feature contracts and evidence-driven backlog | Complete | Documentation setup |
| M1 — Foundation and domain profile | Reproducible workspace, sourced profile and metering history | Complete | Planning baseline |
| M2 — Explainable bills and corrections | End-to-end operator billing with financial integrity | In progress | M1 |
| M3 — Safe legacy migration | Characterisation, shadow comparison and controlled cohort cutover | Planned | M2 |
| M4 — Client variation and market boundary | Second isolated client and bounded integration | Planned | M3 |
| M5 — Operational portfolio delivery | Recovery evidence, Kubernetes and reproducible demonstration | Planned | M4 |

Setup and planning completion refer only to [TAR-001](backlog.md#tar-001) and [TAR-002](backlog.md#tar-002). Core product value is demonstrated at M3; M4 and M5 extend it. Changes to that scope require an explicit record, not silent omission of unfinished extensions.

## M1 — Foundation and domain profile

Independent review at `b5a180f` reopened TAR-004/TAR-005 for format compatibility and ingestion correctness; all five findings remediated and all ten preserved probes now pass. See [review](evidence/m1-exit-review.md).

Scope: TAR-003–005. Create a locked Python/Django/Graphene/Celery and React workspace, real PostgreSQL/RabbitMQ Compose environment, import contracts, minimal CI configuration, frozen supported metering/tariff/time profile and deterministic fixtures with revision ingestion.

Dependencies: TAR-003 may start now. TAR-004 uses the bootstrap environment to freeze numeric/reference and workload gates; source research can begin earlier. TAR-005 requires both.

Exit criteria:

- A clean checkout can install locked dependencies, start the skeleton and run smoke/import-boundary checks.
- Supported format subset, quality/revision precedence, units, time boundaries and rounding are sourced and frozen with independent expected cases.
- Duplicate/corrected/conflicting batches preserve history and deterministic current selection in PostgreSQL.
- Workload and performance acceptance budgets are recorded against the reference environment.

Excludes issuance, ledger, migration and Kubernetes. Gates: [BLK-001](blockers.md#blk-001), [BLK-003](blockers.md#blk-003).

## M2 — Explainable bills and corrections

Current independent verdict at `de0e08d`: In progress. TAR-006/TAR-009 reopened for incomplete rating evidence and account-scoped recovery; the remediation statement below is historical. See the follow-up findings in the [review](evidence/m2-independent-review.md).

Independent review at `2a46650` reopened TAR-006–009 for financial/input integrity and browser/retry failures; all seven findings remediated and the six preserved probes now pass alongside a 102-test suite and a live CSRF-origin-verified portal journey. See [review](evidence/m2-independent-review.md). Re-review of the residual readiness gaps it lists (itemised portal explanation, real broker-fault timing, after-commit/ack kill, bounded query behaviour) remains open evidence work.

Scope: TAR-006–009. Rating engine, durable admission/outbox, atomic invoice/ledger issuance, successive revision adjustments and an authenticated operator journey.

Exit criteria:

- Itemised calculations match independent references under the frozen profile.
- Unique business identities, transactional posting and journal enforcement survive concurrent duplicate requests.
- Repeated and successive meter corrections adjust the net recognised liability without changing issued history.
- Operator import/bill/explain/correct workflow works through the real API, including permission and stale-input errors.
- Broker interruption leaves admitted work recoverable; no false completion is shown.

Excludes legacy cutover, a second client and external market integration. Full process-fault and performance campaigns mature in M5, but tests necessary to establish financial correctness cannot be deferred.

## M3 — Safe legacy migration

Scope: TAR-010–012. Independent legacy calculator, fictional policy/defect fixtures, shadow isolation, versioned comparison evidence and operator cutover.

Exit criteria:

- Legacy and new engines compare equivalent snapshots, detecting line differences even when totals match.
- Shadow attempts cannot write financial records; inconclusive results block evidence.
- Operator preserves a historical policy and approves a scoped legacy-defect correction.
- Stale approvals, concurrent route changes and in-flight issuance cannot bypass cutover gates.
- The cohort journey from legacy to new is reproducible, audited and visible in the portal.

Excludes migration of an entire historical accounting database. Routing rollback concerns future operations only.

## M4 — Client variation and market boundary

Scope: TAR-013–015. Same-image isolated retailers, sourced or explicitly synthetic market workflow, durable adapter and deterministic counterparty simulator.

Exit criteria:

- Client policies differ as intended without cross-client imports, data access or queue access.
- Market transition/protocol profile and limits are frozen before implementation.
- Duplicate, delayed, out-of-order and rejected messages recover or fail according to the transition table.
- Adapter restart and uncertain outcomes reconcile without duplicate business transitions; unrelated billing remains available.

Excludes full MSATS/aseXML conformance and live AEMO connectivity. Gate: [BLK-002](blockers.md#blk-002).

## M5 — Operational portfolio delivery

Scope: TAR-016–018. Correlated diagnostics, process-fault campaign, kind deployment, migration/rollout safety, measured workloads and presentation.

Exit criteria:

- Required [verification scenarios](features/verification.md) have reproducible evidence with no undisclosed failures/skips.
- Forced worker termination before/after commit, outbox interruptions and broker recovery preserve financial invariants.
- Fresh Kubernetes installation, compatible schema migration and failed rollout are demonstrated with explicit availability limits.
- Resource use, throughput/latency and recovery meet the frozen local budgets, or a documented scope revision is accepted.
- Another developer can follow tested setup/reset/demo instructions; a recording and explanation show the full journey and limitations.

Local completion does not imply green hosted CI, cloud deployment or production regulatory readiness. Report each separately. Public hosting, AWS/Terraform/ArgoCD and a second territory remain future candidates.
