# Verification and portfolio evidence

Date: 2026-10-25
Status: Required verification design; no runtime evidence exists yet.

## Evidence matrix

| Scenario | Required evidence | Owning task |
| --- | --- | --- |
| Fresh workspace and enforced module boundaries | Locked install, API/web smoke checks, deliberate forbidden import rejected | TAR-003 |
| Tariff/time/numeric profile | Authoritative format references plus independently worked expected amounts | TAR-004 |
| Meter revision selection | Real PostgreSQL duplicate/conflict/out-of-order cases and reproducible fixtures | TAR-005 |
| Deterministic rating | Independent reference and boundary cases; exact Decimal outcomes | TAR-006 |
| Atomic issuance and adjustments | Transaction/concurrency tests, balance checks, successive corrections | TAR-007, TAR-008 |
| Core operator journey | Browser/API flow and permission-negative cases | TAR-009 |
| Legacy characterisation | Independent legacy/new results for policy and seeded defect | TAR-010 |
| Safe shadow and cutover | Restricted-write tests, stale/inconclusive evidence, cutover/billing race | TAR-011, TAR-012 |
| Two isolated clients | Same-image evidence; database, queue and request isolation checks | TAR-013 |
| External workflow | Deterministic failure/reordering scenarios against real service processes | TAR-014, TAR-015 |
| Recovery and diagnostics | SIGKILL before/after commit, broker outage and outbox recovery; correlated telemetry | TAR-016 |
| Kubernetes delivery | Fresh kind cluster, migration Job, failed rollout, graceful/forced worker termination | TAR-017 |
| Measured portfolio demonstration | Repeated workload timings/resources, clean setup, recording and limitations | TAR-018 |

## Method

Use unit tests for pure calculations, PostgreSQL integration tests for actual constraints and locks, real RabbitMQ/Celery process tests for delivery/recovery, contract tests for external boundaries and browser tests for operator workflows. SQLite substitution and Celery eager mode cannot establish production database/broker behaviour.

A fault test identifies the precise crash boundary, starting state, expected invariant, restart procedure and observed final records. Deliberately attempt duplicate and unauthorised writes. Record both task outcomes and final business state; task success alone does not prove financial integrity.

Use deterministic synthetic fixtures with independent expected answers. Do not derive golden financial results from the production calculator. Record fixture versions, code/image identities, environment, commands, repetitions and limitations. Hosted CI is verified separately from local checks.

## Measurement profile

Proposed workload ladder: three inspectable accounts for explanation, then 100 and 1,000 accounts with 30 days of five-minute synthetic data. The upper rung can exceed eight million intervals per channel and is a capacity experiment, not a prerequisite for a small-machine demo. Freeze required acceptance workload, CPU/memory limits, ingestion throughput, billing latency, API p95 and recovery deadlines in TAR-004 after a bootstrap baseline. [BLK-003](../blockers.md#blk-003) tracks this gate.

No arbitrary throughput or zero-downtime guarantee is established by this plan. Demonstrate API responsiveness during ingestion, bounded queue growth, graceful drain, forced-crash recovery and repeatability against the declared environment. Scaling must preserve correctness, not just improve throughput.

## Delivery and review

Every milestone has an exit review against its roadmap criteria. Evidence can reopen tasks; do not mark them Done solely because implementation exists. The final demonstration includes a written walkthrough, short recording, reproducible reset, architecture explanation and explicit exclusions. Clean local operation is the delivery target; public hosting and live market conformance are not implied.
