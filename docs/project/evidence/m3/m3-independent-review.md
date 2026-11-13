# Independent M3 review

Date: 2026-10-25. Reviewed HEAD: `c06e1fc`, including M2 remediation `6e491ae` and M3 commits `370ed54`, `2ea4fb5`, `c06e1fc`.

## Verdict

M3 remains **In progress**. Reopen TAR-010–012 for the findings below. The independent legacy service, restricted shadow credential, itemised comparison, role checks and basic routing journey are implemented, but the policy-preservation and safe-cutover criteria are not satisfied. Original implementer evidence in [m3-exit-review.md](m3-exit-review.md) is retained as history.

The earlier M2 findings pass their saved regressions: 18 M1/M2 probes pass, including rating-line insertion protection and tariff-window digest changes. Code inspection confirms account-panel remounting and account/period-keyed pending intents with identity-specific clearing. These earlier findings are closed for their tested scope; the M3 billing integration regressions below belong to TAR-012.

## Findings

### R1 — P1: “Preserve client policy” permits dropping the policy

Location: `src/taryx/core/migration/services.py:235–243` (`evaluation_blockers`).

Both classifications simply add fingerprints to the accepted set. A preserve-policy decision does not require the new engine to implement the policy or block its removal. Reproduction: compare ACC-003, classify its GST differences as preserve-client-policy, approve the defect differences, cut over, then bill. The new invoice charges **$0.78 GST** despite the preserved fictional heritage exemption. No legacy invoice exists in this probe, so it directly tests new issuance after migration.

Require preserved policy to be implemented and evidenced in the new calculation before cutover (or retain legacy routing until it is). A classification is not evidence that preservation occurred. Add an end-to-end financial assertion after cutover, not only an assertion that the gate opens.

### R2 — P1: Input changes can commit between gate validation and cutover

Location: `src/taryx/core/migration/services.py:267–295` (`transition_cohort`).

The transaction locks the cohort row, but not the account/input rows participating in freshness validation. In a separate connection, ingestion can commit a revision after `evaluation_blockers` computes a clean result and before the route is saved. The deterministic probe interleaves a real `day1_rev1.nem12` ingestion at that point: NEW_ONLY commits using now-stale evidence instead of rejecting or serialising the revision.

Hold a shared input/admission revision protocol through the route commit and revalidate under it. Include concurrent membership, admission and evidence changes when testing this boundary; the existing sequential pending-operation test does not establish concurrency safety.

### R3 — P1: Legacy engine upgrades reuse old comparison and decision identity

Location: `src/taryx/core/migration/legacy_adapter.py:61–63` (`LegacyResult.version_token`), consumed by `services.py:132–145`.

The token contains engine name and catalogue version, but **omits engine_version**. Returning the same snapshot/catalogue under engine 2.0.0 after 1.0.0 resolves to the same ComparisonRun, retaining the old report and linked calculation. Existing scoped decisions can therefore remain valid across an arithmetic engine upgrade. The probe changes only engine_version and observes the same comparison PK.

Include every relevant engine/catalogue/policy version in comparison identity and approval scope, and require evidence for the deployed version at cutover. Preserve old evidence rather than silently reusing it.

### R4 — P2: A successful retry cannot supersede an earlier comparison failure

Location: `src/taryx/core/migration/services.py:132–145` and `evaluation_blockers` latest-created selection.

Sequence: successful comparison, transient unavailable response, successful retry of the unchanged snapshot. Success uses get_or_create and returns the first success row with its original timestamp; the newer unavailable row remains the latest. The gate stays `inconclusive: ACC-001 comparison failed (unavailable)` indefinitely, despite recovery. Re-freezing the evaluation window has a related inability to produce fresh observations for unchanged inputs.

Separate stable calculation/comparison identity from attempt/observation freshness. Retain failed attempts while letting a later verified success become the latest observation for gate evaluation.

### R5 — P2: The documented outbox command cannot recover legacy billing

Location: `src/taryx/composition/management/commands/drain_outbox.py:11`.

The Celery drain wrapper injects routing and legacy calculation callbacks, but the management command still passes only digest_resolver. With a pending legacy operation, `call_command('drain_outbox')` raises `CalculationUnavailable: no legacy calculator configured for legacy routing`. It also omits routing revalidation. This breaks the broker-outage recovery path precisely when the broker task cannot be used.

Use the same fully composed dependencies in all recovery entry points, and test command execution against pending LEGACY_ONLY and SHADOW operations.

### R6 — P2: Billing after cutover treats a different authoritative result as a duplicate

Location: `src/taryx/core/billing/services.py:368–371`.

Generation equality only checks the new-engine input digest. Issue ACC-001 under legacy ($8.68), approve its defect correction and cut over, create a fresh rating run with the same inputs, then explicitly bill/correct under NEW_ONLY ($8.65). The operation completes with the original invoice and no adjustment because the input digest is unchanged. The authoritative engine/result changed, but the financial generation identity did not. This is an explicit subsequent correction request, not a request for automatic retroactive rewriting on cutover.

Pin authoritative calculation identity/version/result on financial generations and distinguish retries from changed authoritative results. Preserve old invoices and reconcile changed liability through the normal adjustment path. Assert the expected −$0.03 adjustment for this fixture.

### R7 — P2: Portal approval display ignores version/snapshot scope

Location: `web/src/App.tsx:603` and `638–645`.

The UI builds a set of all decision fingerprints and labels every matching diff “decided,” hiding its decision controls. Backend validity additionally depends on snapshot and engine/policy versions. After a reading revision that leaves one export discrepancy unchanged, that discrepancy keeps its fingerprint but needs a new scoped decision; the gate rejects the old approval while the portal still labels it decided and offers no reapproval button. Comparisons are also displayed without evaluation-period filtering.

Expose validity against each current comparison, display stale decisions explicitly, and allow a new version-scoped decision. This finding is source-inspected; no automated browser stale-approval sequence was executed.

### R8 — P2: Malformed JSON shapes escape the inconclusive path

Location: `src/taryx/core/migration/legacy_adapter.py:117–120` and `152–158`.

Valid JSON is not necessarily a valid response object. `[]` raises AttributeError at result.get; a protocol-correct object with empty lines/zero totals but missing engine metadata raises KeyError while constructing LegacyResult outside the protected parsing block. Both propagate through run_comparison without a persisted INCONCLUSIVE row, leaving any prior gate evidence untouched. The two parameterised probes reproduce these exceptions via mocked HTTP response bodies.

Validate the complete response shape/metadata and numeric domain before use; normalise invalid responses into LegacyFailure('malformed') so every failed comparison attempt is persisted and blocks evaluation until recovery.

## Verification

- `make check` **fails** at Ruff format: `src/taryx/core/migration/seed.py` and `tests/test_migration.py`. Ruff lint passes. The implementer's green-check claim does not hold at reviewed HEAD.
- Continued with `make typecheck contracts test web-check`: **passed**, including mypy, import contracts and deliberate negative probe, **131 pytest tests**, **6 frontend tests**, TypeScript and production build.
- Saved M1/M2 probe command: **18 passed** (`m1_review_probes.py`, `m2_review_probes.py`, `m2_followup_probes.py`, with `-c pyproject.toml`).
- [m3_review_probes.py](m3_review_probes.py): eight failing cases covering R1–R6 and the two R8 malformed shapes. Run with `uv run pytest docs/project/evidence/m3/m3_review_probes.py -c pyproject.toml -q`. Uses real PostgreSQL and an independently launched legacy-sim subprocess; mocks only upgrade response metadata, malformed response bodies and the deterministic gate interleaving hook. R2's competing ingestion uses a separate database connection.
- Local Compose api/worker/web/legacy rebuilt without resetting volumes. Actual browser renders authenticated accounts, migration cohort r4, itemised decisions and the existing malformed-response blocker. No cutover was performed against the persistent demo database. Browser stale-approval automation and a full process-kill campaign were not performed.
- Review adds evidence/probes and project-record changes only. No application fixes, commits or pushes.

## Next action

Resolve R1–R8 and the formatter gate, fold meaningful probes into the normal suite, then re-review cutover and recovery before beginning M4. Keep prior decisions/evidence and financial records intact.

## Remediation addendum — 2026-10-25

All eight findings resolved and verified; probes folded into `tests/test_migration.py` (nine new regressions).

- **R1**: `TariffSpec.gst_exempt` implemented; engine honours it and the digest payload pins it; `T-FLAT-FIT-HERITAGE` now carries the preserved exemption under catalogue `2026-10-25.3`. The gate reports `unpreserved_policy` when a valid preserve decision's fingerprint still appears in the latest evidence — preservation must be implemented and evidenced, not merely classified. Live: ACC-003 rates gst 0 / total 7.27; only the FIT truncation remains.
- **R2**: `transition_cohort` revalidates after gate evaluation under member account `select_for_update` locks — input digests and policy identity re-verified, in-flight ops re-checked; concurrent revisions serialize on the account lock (commit before the lock is seen as stale, commit after lands post-cutover).
- **R3**: `version_token` now includes `engine_version`; an engine upgrade produces a new comparison identity and invalidates scoped decisions.
- **R4**: `ComparisonRun.updated_at` separates stable comparison identity from observation freshness — `update_or_create` refreshes conclusive evidence so a re-verified success supersedes an intervening failed attempt; failed attempts are retained. Freshness is evaluated on `updated_at`.
- **R5**: `drain_outbox` command composes the same `routing_resolver`/`legacy_calculator` dependencies as the Celery task; verified live recovering a pending operation.
- **R6**: `calculation_source` recorded on `Invoice` and `Adjustment`; generation identity is (engine source, input digest) — a changed authoritative engine reconciles through the normal adjustment path. Live: ACC-003 new-engine billing after cutover produced ADJ-000003 (delta 0.00, audit evidence) preserving INV-000002.
- **R7**: `DecisionType.valid` exposes scope validity against the latest evidence carrying each fingerprint; the portal filters comparisons to the evaluation window, labels stale decisions and offers re-approval.
- **R8**: `_parse` validates object shape and metadata inside the failure boundary — non-object and missing-metadata bodies normalise to `LegacyFailure("malformed")` and persist INCONCLUSIVE.
- **Format gate**: `ruff format` applied; `make check` is green end-to-end (140 pytest, 6 vitest, typecheck, build, mypy, import contracts, formatter).

Verification: 8/8 preserved probes pass; 140 pytest on real PostgreSQL; live re-verified (policy-evidenced comparison, clean gate, guarded cutover, zero-delta generation-change adjustment, CLI outbox recovery).


## Independent remediation re-review — `f9f21df`, 2026-10-25

Verdict: **M3 remains In progress**. The eight original M3 probes now pass, as do all earlier M1/M2 probes. The preserved heritage GST policy, legacy comparison version token, CLI outbox composition, first post-cutover correction, original malformed shapes and original input-revision interleaving are fixed for the exercised cases. Portal validity/period-filter changes were inspected in source; no new browser campaign was performed in this re-review.

Four remaining findings (five failing cases) prevent closure:

### F1 — P1: A later failed comparison no longer blocks cutover (R4 regression)

`src/taryx/core/migration/services.py:215–226` discards every INCONCLUSIVE row before selecting current evidence. Compare successfully and approve differences, then run a comparison that returns unavailable: `evaluation_blockers` returns no inconclusive blocker, even though no successful recovery attempt has occurred. This reverses the required failure semantics. Select the latest observation of any status; `updated_at` should allow a later success to supersede failure, not allow an earlier success to conceal it. The final validation must use the same rule.

### F2 — P1: Final cutover validation does not recheck approval scope (R2 incomplete)

`src/taryx/core/migration/services.py:313–342` selects a fresh comparison under the final account locks, but checks only input digest and policy identity. If a comparison for legacy engine 2.0.0 arrives after the initial gate approved 1.0.0 and before the final check, it has the same inputs/policy but no valid decisions. Cutover nevertheless commits. The deterministic probe inserts that independently versioned comparison at the validation boundary and observes NEW_ONLY instead of rejection. Re-evaluate the complete gate against a pinned, consistent evidence/decision revision through commit, including failure status, engine identity, freshness and decisions; do not replace it with a partial digest check.

### F3 — P2: A second routing-change correction violates adjustment uniqueness (R6 incomplete)

`src/taryx/core/billing/models.py:115–116` still makes (invoice, input_digest) unique, despite services now allowing the same inputs under a changed calculation source. Reproduction: issue legacy; cut over and explicitly correct under new; roll back and explicitly correct under legacy, with fresh rating runs and unique operation IDs. The first correction succeeds, but the rollback correction raises `IntegrityError` on `uniq_adjustment_digest` and leaves the operation pending. Use a financial generation identity/constraint that supports legitimate successive engine transitions while retaining retry idempotency. Merely adding source to the key also needs testing for repeated legacy→new→legacy→new cycles.

### F4 — P2: Malformed response values still bypass INCONCLUSIVE persistence (R8 incomplete)

`src/taryx/core/migration/legacy_adapter.py:110–114,148,153–157` handles absent fields and non-object bodies but not invalid field values. A complete zero-total response with `engine_version: null` reaches database persistence and raises a NOT NULL IntegrityError; `net: "sNaN"` raises decimal.InvalidOperation during reconciliation. Neither persists an INCONCLUSIVE comparison. Validate required metadata types/nonempty version identities and finite decimals inside the failure boundary, normalising bad values to LegacyFailure('malformed') before arithmetic or database writes.

### Verification

- `make check`: **passed** end-to-end, including formatter/lint, mypy, import contracts/negative probe, **140 backend tests**, **6 frontend tests**, typecheck and build.
- Saved M1/M2/M3 review probes: **26 passed** in 25.84s.
- [m3_followup_probes.py](m3_followup_probes.py): **5 failed**, covering F1–F4 (F4 has two cases). Command: `uv run pytest docs/project/evidence/m3/m3_followup_probes.py -c pyproject.toml -q`. Uses existing portable helpers, real PostgreSQL and the independently launched legacy service; engine-arrival timing and malformed HTTP bodies are controlled test inputs.
- No application fixes, commits or pushes. Updated evidence/status/journal only. Earlier findings remain historical; this section supersedes the implementer addendum's closure claim.

Next action: resolve F1–F4 and rerun the saved probes plus normal checks before M4.

## Second remediation addendum — 2026-10-25

F1–F4 resolved; all five follow-up probes pass and are folded into `tests/test_migration.py`.

- **F1**: the gate selects the latest observation of ANY status by `updated_at` — a failure after the last success blocks with `inconclusive:` until a re-verified success refreshes the conclusive row's `updated_at` and supersedes it. Verified live (unavailable → inconclusive blocker; retry → clean gate).
- **F2**: `transition_cohort` re-runs the COMPLETE `evaluation_blockers` under member account locks (plus the in-flight check) before committing NEW_ONLY — evidence/decision/membership/input changes committed during the first evaluation are re-evaluated in full, not partially.
- **F3**: `uniq_adjustment_digest` removed; `(invoice, generation)` is the financial generation identity. Successive engine transitions (legacy→new→legacy→…) reconcile through the normal adjustment path; retry idempotency is the recognised-generation check under the operation + invoice locks. Verified live: rollback produced ADJ-000005 (delta 0.00).
- **F4**: `_decimal` rejects non-finite values; reconciliation arithmetic runs inside the failure boundary (InvalidOperation → malformed); all five metadata fields must be non-empty strings — both `sNaN` and null-version bodies now persist INCONCLUSIVE.

Verification: 13/13 preserved M3 probes (8 original + 5 follow-up); 145 pytest total; ruff/format/mypy/import contracts clean. Live: rollback-correction cycle and failure-blocking semantics re-verified against the real legacy service.


## Independent re-review — `db18588`, 2026-10-25

Verdict: **one P1 finding remains in F2; M3 stays In progress**. F1 (latest failure), F3 (rollback correction uniqueness) and F4 (invalid response values) pass their original probes. The previous F2 interleaving before the second gate also passes. TAR-010 remains Done; TAR-011/TAR-012 are reopened for the remaining cutover boundary.

### P1 — Evidence updates can still commit after final validation

Locations: `src/taryx/core/migration/services.py:63–81` (failed-attempt upsert) and `306–331` (final gate under account locks).

Account locks do not serialize updates to existing ComparisonRun rows. The shadow connection updates these rows without taking the same account/revision lock; unchanged foreign-key values do not force a conflicting account-row lock. Reproduction:

1. Record an unavailable comparison, then a successful retry and valid decisions. The gate is clean.
2. Begin cutover and let its second, complete gate evaluation read that successful evidence while holding account locks.
3. Before the route commit, publish another failed attempt by updating the existing unavailable row through the actual shadow database connection.
4. The update commits without waiting; cutover nevertheless commits NEW_ONLY using its earlier clean result.

[m3_commit_window_probe.py](m3_commit_window_probe.py) deterministically reproduces this transaction interleaving with real PostgreSQL connections. It accepts either blocked evidence publication (bounded by a two-second statement timeout) or rejected cutover; current code does neither. The legacy failure is injected at the adapter boundary; successful evidence comes from the independently launched legacy simulator.

Use a shared serialization/revision protocol between cutover and **all gate-affecting writers**, including updates to existing evidence and decisions. Pin the evidence evaluated until the route commits. Adding another unlocked read merely moves the race window. Keep the restricted shadow role's financial-write prohibition intact.

### Verification

- `make check`: passes, including **145 backend tests**, **6 frontend tests**, formatter/lint, mypy, import contracts/negative probe, TypeScript and build.
- All saved M1/M2/M3 probes through `m3_followup_probes.py`: **31 passed**.
- New saved commit-window probe: **1 failed**. Command: `POSTGRES_DB=taryx_review_window uv run pytest docs/project/evidence/m3/m3_commit_window_probe.py -c pyproject.toml -q`. The separate test database allowed this probe to run independently of the main suite; no persistent demo financial data changed.
- No new browser campaign; this re-review targets the changed backend safety boundary. No application fixes, commits or pushes.

Next action: complete F2's serialization guarantee, then rerun the saved probes and normal checks. Earlier findings and implementer addenda remain historical.


## Third remediation addendum — 2026-10-25

F2's remaining commit-window race is resolved by a shared serialization protocol: a transaction-scoped advisory lock (`pg_advisory_xact_lock(ns, cohort_id)`) keyed on the cohort, taken by **every gate-affecting writer** before it commits — `run_comparison` (failed-attempt upserts and `_persist_comparison`, which also covers the SHADOW billing path), `decide_discrepancy`, and the seeded membership `set`. `transition_cohort` acquires the same lock after the member account locks and holds it across the full final gate re-read through the route commit. Lock ordering is consistent (account rows → advisory), so no deadlock cycle exists with the billing path. Advisory locks need no table privileges — the restricted `taryx_shadow` role takes them on the same database, and its financial-write prohibition is unchanged.

An evidence write now either commits before the lock is held (then the complete re-evaluation sees and rejects it) or blocks until after the route commit — nothing can land inside the window. The `m3_commit_window_probe.py` case passes via blocked publication bounded by its statement timeout.

Verification: the commit-window probe plus all 13 preserved M3 probes pass; the probe is folded into `tests/test_migration.py` alongside the updated F2 race case (32 migration tests); 146 pytest total; format/lint/mypy/import contracts clean. Verified live: a comparison write through the API container blocked 6.7s on a manually held cohort gate lock, then committed — the protocol serializes against the real database and credentials.


## Fourth remediation addendum — 2026-11-08 (loop round 1)

Codex round 1 (`codex exec resume`, read-only thread — verdict in `m3-verdict-r1.txt`): **CHANGES_REQUESTED**, one P2 — cutover locks member account rows `FOR UPDATE` before acquiring the advisory gate lock, while evidence writers acquire the same locks in reverse through foreign-key checks (`FOR KEY SHARE` on the account row after the advisory lock). PostgreSQL aborts either side with `deadlock detected` — reproduced by the preserved `m3_gate_deadlock_probe.py`.

**Resolution**: the member account locks and the cohort row lock in `transition_cohort` are now `FOR NO KEY UPDATE`. That strength still blocks every input mutator (ingestion, `lock_inputs`, billing ops all take `FOR UPDATE`) and serializes concurrent transitions, but does NOT conflict with the `FOR KEY SHARE` locks that evidence/decision/membership inserts take implicitly through FK checks — so a writer holding the gate lock can never be queued behind a row lock the cutover holds. The earlier parent-lock-first alternative was rejected: the restricted `taryx_shadow` role has no privilege to take row locks on `accounts_account` at all, and the billing path intentionally persists evidence before `lock_inputs` runs.

`decide_discrepancy` and the seeded membership `set` keep explicit parent-row locks before the gate lock (consistent cohort → accounts → advisory ordering on the default connection).

Verification: `m3_gate_deadlock_probe.py` and `m3_commit_window_probe.py` pass unchanged in intent (the deadlock probe's instrumentation is restored — the writer can once again hold the advisory mid-window without deadlocking); 13/13 preserved probes + 32 migration tests + 146 pytest; format/lint/mypy/contracts green; live seed + comparison + gate re-verified.


## Fifth remediation addendum — 2026-11-08 (loop round 2)

Codex round 2 (`m3-verdict-r2.txt`): **CHANGES_REQUESTED**, one P1 — `admit_issue` took neither an account lock nor the gate lock, so a billing operation could be admitted under the old routing pin after the final pending-operations check but before the route commit; `process_operation` revalidated routing before `lock_inputs`, not under it, so the op could then issue legacy amounts after `NEW_ONLY` committed. Source-confirmed interleaving; runnable probe `m3_admission_cutover_probe.py`.

**Resolution**:

- `admit_issue` now takes `routing_resolver` instead of explicit `cohort_mode`/`cohort_revision` and resolves the pin **inside** its atomic while holding the account row `FOR UPDATE` — which conflicts with the cutover's member `NO KEY UPDATE` locks. Admission either commits before the member locks (visible to the pending check → `in_flight`) or waits and pins the post-commit routing.
- `process_operation` revalidates the routing pin a second time **after `lock_inputs`** — a cutover committed during the lock wait marks the op `stale` instead of issuing under the old pin.
- Callers (`bill_account` command, GraphQL `billAccount`) pass `routing_resolver=routing_for`; the billing layer keeps its DI boundary (no migration import).

Verification: `m3_admission_cutover_probe.py` passes and is folded into `tests/test_migration.py` (33 migration tests); 13/13 preserved probes; 146 pytest; format/lint/mypy/contracts green.


## Sixth remediation addendum — 2026-11-08 (loop round 3)

Codex round 3 (`m3-verdict-r3.txt`): **CHANGES_REQUESTED**, one P1 — member locks and the final pending-operations check sat inside the `to_mode == NEW_ONLY` branch, so `NEW_ONLY → LEGACY_ONLY` could change routing while a newly admitted worker held its issuance locks; the worker's routing re-check cannot protect against a transition that ignores its lock.

**Resolution**: member locks (`NO KEY UPDATE`), the shared gate lock and the pending-operations recheck now apply to **every** routing transition; only `evaluation_blockers` remains `NEW_ONLY`-specific. Rollback serializes with admission and issuance identically to cutover.

Verification: the appended `test_rollback_serializes_with_new_billing` probe passes and is folded into `tests/test_migration.py` (34 migration tests); full `make check` re-run.


## Review-loop closure — 2026-11-08 (round 4)

Codex round 4 (`m3-verdict-r4.txt`): **verdict: APPROVED** — no remaining blocking findings. Every routing transition now serializes admission, issuance and evidence writes; the earlier admission, issuance and evidence protections stand. TAR-011/TAR-012 and M3 are complete.

Loop summary (4 rounds, all findings remediated and folded into `tests/test_migration.py`): P2 gate-lock deadlock → `FOR NO KEY UPDATE` row locks; P1 admission/cutover race → `admit_issue` resolves routing under the account lock + routing revalidation under `lock_inputs`; P1 rollback bypass → serialization for every transition. Reviewer verification limitation retained: the Codex thread ran read-only, so findings and verdicts arrived via `-o` files and addenda/records were written by Devin.
