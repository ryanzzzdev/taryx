# M3 exit review — safe legacy migration

Date: 2026-10-25. Reviewer: Devin (SWE-2 High), campaign checkpoints TAR-010/011/012.
Scope: [M3 exit criteria](../roadmap.md#m3--safe-legacy-migration). Contract:
[legacy-migration](../features/legacy-migration.md).

Verdict: independent review of `c06e1fc` raised eight findings; all are remediated with the eight preserved probes now passing as permanent regressions — see [independent review](m3-independent-review.md#remediation-addendum--2026-10-25). The evidence below is the original implementer assessment, retained as history.

## Criterion 1 — Equivalent snapshots, line differences even when totals match

- Both engines consume `RatingRun.input_snapshot` — the same immutable payload is
  serialised into the versioned `taryx-legacy/1` request (`legacy_adapter.build_request`)
  and was the rating input.
- `comparison.diff_lines` pairs lines by component identity and reports per-field
  differences (quantity, rate, amount, gst) plus bill totals; every diff carries a
  stable fingerprint.
- `tests/test_migration.py` covers an offsetting-difference case where component
  diffs net to an equal total and still report DIFFERENCE.
- Live: ACC-001 shadow comparison over real HTTP reported 4 itemised diffs
  (export quantity 9.6→9, amount −0.48→−0.45, net, total); ACC-003 reported 5
  (export quantity, GST exemption on import/supply, gst_total, total).

## Criterion 2 — Shadow cannot write financial records; inconclusive blocks evidence

- Migration `migration/0001` creates role `taryx_shadow` (SELECT everywhere; INSERT
  only on evidence tables) mapped to the `shadow` DB alias. Exercised: actual
  `permission denied for table billing_invoice` on INSERT/DELETE, evidence-table
  writes succeed (tests + live psql).
- Timeout, malformed response, unavailable service and protocol mismatch persist
  INCONCLUSIVE rows; `evaluation_blockers` reports `inconclusive:` per member.
- Live: injected `malformed` fault on legacy-sim produced an INCONCLUSIVE
  comparison and the gate blocked with `inconclusive: ACC-001 comparison failed
  (malformed)`; state restored afterwards.

## Criterion 3 — Preserve a historical policy and approve a scoped defect correction

- `decide_discrepancy` records a `DiscrepancyDecision` scoped to the diff
  fingerprint, snapshot hash, engine versions and policy identity of the evidence
  it saw; it cannot bless a fingerprint absent from cohort evidence.
- Live over real sessions: operator recorded `approved_defect_correction` for the
  FIT-TRUNC-2003 quantity/amount/totals fingerprints on both members, and
  `preserve_client_policy` for the heritage GST-exemption fingerprints on ACC-003,
  each with a reason. Decisions are GraphQL-visible on the cohort.

## Criterion 4 — Stale approvals, concurrent route changes, in-flight issuance cannot bypass gates

- Decision validity is evaluated against the latest evidence (`is_valid_for`) —
  changed inputs, engine or policy versions invalidate approvals.
- `transition_cohort` enforces an optimistic `expected_revision` check, rejects
  unknown mode edges, blocks when any member has a PENDING billing operation, and
  gates NEW_ONLY on the frozen evaluation — all inside `select_for_update`.
- Billing operations pin `cohort_mode`/`cohort_revision` at admission;
  `process_operation` revalidates routing under `lock_inputs` and raises
  `stale_routing` on mismatch (unit-tested).
- Live: `expectedRevision: 99` returned `stale_revision`; a synthetic PENDING op
  returned `in_flight` and blocked rollback until drained.

## Criterion 5 — Reproducible, audited, portal-visible cohort journey

- Live journey exercised end to end over session-authenticated GraphQL:
  approver `legacy_only → shadow` (r2); operator `billAccount` ACC-003 issued
  INV-000002 at the **legacy** total 7.27 (new engine computed 8.05) with the
  comparison persisted; 9 scoped decisions recorded; in-flight guard blocked
  rollback until drained; approver `shadow → new_only` (r3) passed the gate;
  approver `new_only → legacy_only` rollback (r4). `cohortEvents` returns the
  full audited history.
- Portal: `MigrationPanel` (web/src/App.tsx) renders cohorts with mode/revision,
  eval window, gate blockers, per-account comparison status/failure code and
  itemised diffs; decisions show classification/actor inline; operator/approver
  may decide diffs, approver may drive shadow/cutover/rollback — all through
  payload-code mutations that surface server-side guard failures.
- 17 new tests across migration routing and GraphQL; 131 pytest total, vitest 6,
  typecheck, build, ruff, mypy and import contracts green.

## Residual limitations (recorded, not blocking)

- Inconclusive-state portal coverage is verified via GraphQL/evidence rows rather
  than a browser automation harness — no such harness exists in the project.
- Shadow-mode billing runs the legacy call synchronously inside the worker; a
  hanging legacy blocks the task until `LEGACY_TIMEOUT_SECONDS`, leaving the op
  pending (retriable), which is the intended bounded-failure behaviour.
- The demo freeze timestamp was backdated once during live verification after a
  seed re-run re-froze the window post-evidence; freeze semantics themselves are
  enforced and tested.
