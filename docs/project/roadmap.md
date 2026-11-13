# Taryx roadmap

Date: 2026-10-25

This is the initial delivery sequence, not a calendar commitment. The earlier 6–10 week ambition is a sizing hypothesis; reassess after M1 and M3. [Backlog](backlog.md) owns task status; [architecture](architecture.md) owns design. M1 metering completion is confirmed by the 2026-11-08 round-two independent review; prior billing approval is retained.

| Milestone | Outcome | Status | Depends on |
| --- | --- | --- | --- |
| Documentation setup | Portable Cateniq-style workflow | Complete | None |
| Planning baseline | Architecture, feature contracts and evidence-driven backlog | Complete | Documentation setup |
| M1 — Foundation and domain profile | Reproducible workspace, sourced profile and metering history | Complete | Planning baseline |
| M2 — Explainable bills and corrections | End-to-end operator billing with financial integrity | Complete | M1 |
| M3 — Safe legacy migration | Characterisation, shadow comparison and controlled cohort cutover | Complete | M2 |
| M4 — Client variation and market boundary | Second isolated client and bounded integration | In progress | M3 |
| M5 — Operational portfolio delivery | Recovery evidence, Kubernetes and reproducible demonstration | Planned | M4 |

Setup and planning completion refer only to [TAR-001](backlog.md#tar-001) and [TAR-002](backlog.md#tar-002). Core product value is demonstrated at M3; M4 and M5 extend it. Changes to that scope require an explicit record, not silent omission of unfinished extensions.

## M1 — Foundation and domain profile

Latest metering review: **approved** at `e8fda0ccfb83c7ddd976771b0166eb5d8beb7ec5` on 2026-11-08. M1-F1–F4 resolved; 17 independent probes and full checks pass (159 backend/6 frontend). TAR-005/TAR-006 completion confirmed. [Review and retained limits](evidence/m1/m1-metering-independent-review.md). Earlier reopening statements below are historical.

2026-11-08 metering review: **changes requested** at `230dc0f1078243e3448ecc145c842228b22cca8c`; TAR-005/TAR-006 reopened for M1-F1–F4 and remediated the same day (parser metadata validation, explicit repeated-day rejection, equivalent-revision selection no-op, snapshot-coherent coverage). [Evidence and probes](evidence/m1/m1-metering-independent-review.md). The user-defined review scope includes TAR-003–006 (rating was historically grouped under M2 below). Historical completion statements are superseded for metering/rating only; the approved billing review is unchanged.

Independent review at `b5a180f` reopened TAR-004/TAR-005 for format compatibility and ingestion correctness; all five findings remediated and all ten preserved probes now pass. See [review](evidence/m1/m1-exit-review.md).

Scope: TAR-003–005. Create a locked Python/Django/Graphene/Celery and React workspace, real PostgreSQL/RabbitMQ Compose environment, import contracts, minimal CI configuration, frozen supported metering/tariff/time profile and deterministic fixtures with revision ingestion.

Dependencies: TAR-003 may start now. TAR-004 uses the bootstrap environment to freeze numeric/reference and workload gates; source research can begin earlier. TAR-005 requires both.

Exit criteria:

- A clean checkout can install locked dependencies, start the skeleton and run smoke/import-boundary checks.
- Supported format subset, quality/revision precedence, units, time boundaries and rounding are sourced and frozen with independent expected cases.
- Duplicate/corrected/conflicting batches preserve history and deterministic current selection in PostgreSQL.
- Workload and performance acceptance budgets are recorded against the reference environment.

Excludes issuance, ledger, migration and Kubernetes. Gates: [BLK-001](blockers.md#blk-001), [BLK-003](blockers.md#blk-003).

## M2 — Explainable bills and corrections

Latest foundation review: **approved** at `2704f119` on 2026-11-08 after the authorised resumed fourth round. F1–F4 resolved; canonical M2 completion confirmed for this scope with 155 backend/6 frontend tests and 25 independent probes passing. [Review](evidence/m1/m1-independent-review.md) retains browser and operational verification limits; historical reopening statements below are superseded. This is not a separate M3 or release-readiness approval.

Round-three foundation review at `e809640` (2026-11-08): **changes requested** — F3 persisted legacy rendering and F4 mutable authoritative provenance; both remediated same day (evidence immutability trigger + persisted line shape) and folded into the suite. See [review](evidence/m1/m1-independent-review.md); later evidence supersedes historical completion statements below.

Round-two independent review at `c270a322` (2026-11-08): **changes requested**; F1 resolved, F2 retry-exhaustion recovery and F3 authoritative legacy explanation remain open. TAR-007/TAR-009 reopened; see [review](evidence/m1/m1-independent-review.md). Required checks pass but two new independent probes fail.

2026-11-08 foundation re-review (user-labelled M1) at `c88b722`: **changes requested**, reopening TAR-007/TAR-009 for empty journals, outbox starvation and missing portal bill explanation; round 2 verified F1 and found retry-exhaustion and legacy-explanation gaps — all findings remediated same day and all probes folded into the suite. See [independent review](evidence/m1/m1-independent-review.md). Earlier completion/remediation statements below remain historical.

Independent re-review at `de0e08d` reopened TAR-006/TAR-009 for incomplete rating evidence and account-scoped recovery; all four follow-up findings remediated and both preserved probes pass. See the [review](evidence/m2/m2-independent-review.md).

Independent review at `2a46650` reopened TAR-006–009 for financial/input integrity and browser/retry failures; all seven findings remediated and the six preserved probes now pass alongside a 102-test suite and a live CSRF-origin-verified portal journey. See [review](evidence/m2/m2-independent-review.md). Re-review of the residual readiness gaps it lists (itemised portal explanation, real broker-fault timing, after-commit/ack kill, bounded query behaviour) remains open evidence work.

Scope: TAR-006–009. Rating engine, durable admission/outbox, atomic invoice/ledger issuance, successive revision adjustments and an authenticated operator journey.

Exit criteria:

- Itemised calculations match independent references under the frozen profile.
- Unique business identities, transactional posting and journal enforcement survive concurrent duplicate requests.
- Repeated and successive meter corrections adjust the net recognised liability without changing issued history.
- Operator import/bill/explain/correct workflow works through the real API, including permission and stale-input errors.
- Broker interruption leaves admitted work recoverable; no false completion is shown.

Excludes legacy cutover, a second client and external market integration. Full process-fault and performance campaigns mature in M5, but tests necessary to establish financial correctness cannot be deferred.

## M3 — Safe legacy migration

Latest independent verdict (2026-11-08 UTC): **approved** at `64ace7dda5a44ddede4a91f74d54eb85e03bfbe8`.
M3 is **Complete**; TAR-010–012 completion confirmed. M3-RR-F1/F2 and the
round-two boundary gaps are resolved; 25 preserved probes and full checks pass
(197 backend/6 frontend). [Resumed review and limits](evidence/m3/m3-re-review.md#round-two-resumed-independent-verification).
The statements below are historical; M4 review remains separate.

Latest verdict (2026-11-08): **changes requested** at
`7d6c633285d98ed7afd0ed42c8c873a55c4f9faf`; M3-RR-F1/F2 (incomplete legacy output
and malformed line identities) remediated the same day — strict per-field line
validation plus import-usage completeness reconciliation route both defect
classes through `malformed` → INCONCLUSIVE evidence / terminal FAILED operation.
All three probes folded into `tests/`; full checks pass (164 backend/6 frontend).
[Fresh review](evidence/m3/m3-re-review.md) — a re-review round is pending.

Current verdict: Complete. The last F2 commit-window race is remediated — the commit-window probe and all 13 preserved M3 probes pass; see the [third remediation addendum](evidence/m3/m3-independent-review.md#third-remediation-addendum--2026-10-25). Earlier verdicts below are historical.

Scope: TAR-010–012. Independent legacy calculator, fictional policy/defect fixtures, shadow isolation, versioned comparison evidence and operator cutover.

Exit criteria (verified — see [implementer review](evidence/m3/m3-exit-review.md) and the remediated [independent review](evidence/m3/m3-independent-review.md)):

- Legacy and new engines compare equivalent snapshots, detecting line differences even when totals match.
- Shadow attempts cannot write financial records; inconclusive results block evidence.
- Operator preserves a historical policy and approves a scoped legacy-defect correction.
- Stale approvals, concurrent route changes and in-flight issuance cannot bypass cutover gates.
- The cohort journey from legacy to new is reproducible, audited and visible in the portal.

Excludes migration of an entire historical accounting database. Routing rollback concerns future operations only.

## M4 — Client variation and market boundary

Round 5 at `98fad76`: remediation **approved**, F8 and live code-freshness gap closed; TAR-013 Done. M4/TAR-015 remain In progress for explicit billing-under-market-outage and live adapter-restart exit evidence or accepted allocation to TAR-016. [Review and verification limits](evidence/m4/m4-review-r5.md). Earlier review statements below are historical.

Authorised round 4 at `853842c9ba24c92aa7d487ca3546910eef7107e1`: **changes requested**. F7/F10/F11 reported cases pass; F8 retains a stale-consumer concurrency window. All four live image digests match, but imported market code omits part of the candidate remediation. M4 remains In progress. [Round-4 evidence](evidence/m4/m4-review-r4.md).

Round 3 (2026-11-08): **changes requested** at `4b65cf58`. M4-F5/F9 resolved; F7/F8 remain, with new F10 submission-budget and F11 image-identity gaps. TAR-013/TAR-015 In progress; TAR-014 Done. M4 remains In progress. Three-round cap reached: driver escalation required before another review. [Review](evidence/m4/m4-independent-review.md#round-3--independent-verification-2026-11-08).

Round-3 remediation (2026-11-08): all four findings addressed — boolean `last_seq` recovery rejection, `pending_transfer_id` per-correlation dedup at the core consumer, POST-count attempt budget, and one named `taryx-app:latest` image shared by all four app services (one live digest). `make check` green (221 backend/6 frontend). M4 remains In progress pending independent re-review.

Round 4 (2026-11-08, driver-authorized past the cap): **changes requested** — F7/F10/F11 verified; F8 reproduced once more as a stale-instance check-then-act race. R4 remediation: the correlation check is now atomic inside the conditional `UPDATE` in `apply_transfer_outcome` (plus `clear_pending_transfer`/`begin_transfer`); live image rebuilt to candidate. `make check` green (222 backend/6 frontend).

Round 2 (2026-11-08): **changes requested** at `d1831219`; M4-F5/F7/F8 remain and M4-F9 identifies a shared runtime shadow credential crossing client boundaries. R2 remediation applied all four (durable submit markers, strict correlation/transport validation, core-owned outcome consumer, per-client shadow roles) — probes folded, `make check` green (216 backend/6 frontend). M4 remains In progress pending independent re-review. [Review and remediation](evidence/m4/m4-independent-review.md).

2026-11-08 independent review: **changes requested** at `2dbc5b0`; TAR-013 and TAR-015 reopened for M4-F1–F8. 2026-11-08 R1 remediation applied all eight findings (credential isolation, bounded recovery, guarded transitions, protocol/envelope validation) — probes folded into `tests/test_market.py`, `make check` green (205 backend/6 frontend). M4 remains In progress pending independent re-review. [Findings, probes and remediation](evidence/m4/m4-independent-review.md).

Scope: TAR-013–015. Same-image isolated retailers, sourced or explicitly synthetic market workflow, durable adapter and deterministic counterparty simulator.

Exit criteria:

- Client policies differ as intended without cross-client imports, data access or queue access.
- Market transition/protocol profile and limits are frozen before implementation.
- Duplicate, delayed, out-of-order and rejected messages recover or fail according to the transition table.
- Adapter restart and uncertain outcomes reconcile without duplicate business transitions; unrelated billing remains available.

Excludes full MSATS/aseXML conformance and live AEMO connectivity. Gate: [BLK-002](blockers.md#blk-002) — resolved 2026-11-08 by [decision 005](decisions/005-market-workflow-contract.md).

Status note 2026-11-08: all three scoped tasks implemented and verified (TAR-013/014/015 — see backlog evidence). Milestone stays In progress pending the deferred independent review; M4 review loop was skipped this campaign on Codex quota and is owed before the milestone is claimed complete.

## M5 — Operational portfolio delivery

Scope: TAR-016–018. Correlated diagnostics, process-fault campaign, kind deployment, migration/rollout safety, measured workloads and presentation.

Exit criteria:

- Required [verification scenarios](features/verification.md) have reproducible evidence with no undisclosed failures/skips.
- Forced worker termination before/after commit, outbox interruptions and broker recovery preserve financial invariants.
- Fresh Kubernetes installation, compatible schema migration and failed rollout are demonstrated with explicit availability limits.
- Resource use, throughput/latency and recovery meet the frozen local budgets, or a documented scope revision is accepted.
- Another developer can follow tested setup/reset/demo instructions; a recording and explanation show the full journey and limitations.

Local completion does not imply green hosted CI, cloud deployment or production regulatory readiness. Report each separately. Public hosting, AWS/Terraform/ArgoCD and a second territory remain future candidates.
