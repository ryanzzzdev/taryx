# M3 independent re-review

Latest verdict: **APPROVED** at `64ace7dda5a44ddede4a91f74d54eb85e03bfbe8` (2026-11-08,
resumed round two). M3-RR-F1/F2 and the round-two boundary gaps are resolved.
See [resumed verification](#round-two-resumed-independent-verification).
Earlier findings and implementation assessments below remain historical.

Candidate and verified HEAD: `7d6c633285d98ed7afd0ed42c8c873a55c4f9faf`.
Date: 2026-11-08. Scope: TAR-010–012, safe legacy migration.
Reviewer: Codex (GPT-6 family; exact variant unavailable).

Verdict: **CHANGES_REQUESTED**. The existing suite passes, but the adapter
still accepts missing output and fails to record some malformed responses.
Earlier M3 approvals remain historical; this review reopens TAR-010–012.
No implementation files changed and no commit was made.

## Findings

### M3-RR-F1 — High: missing legacy components are not rejected

Location: `src/taryx/core/migration/legacy_adapter.py:144–157`
(`_parse` and request validation in `calculate`).

A response with valid metadata, the correct snapshot echo, `lines: []`, and
zero net/GST/total passes validation for an ACC-001 snapshot containing usage
and daily supply. Arithmetic reconciliation alone cannot establish that the
requested calculation was returned. The comparison treats missing output as
ordinary, approvable differences. A partial response retaining only the daily
supply component issued `INV-000001` for **1.21**, omitting the usage components
from a snapshot whose new-engine total is **8.65**. This violates the explicit
missing-output/inconclusive contract and permits incorrect authoritative bills
when the satellite returns incomplete but syntactically valid output.

Reject absent required output against the request's supported period/agreement
and component coverage before returning a `LegacyResult`. Retain legitimate
zero-valued calculations with complete output; do not simply require a
positive total. Missing output must persist INCONCLUSIVE comparison evidence
and prevent authoritative issuance. Probes:
`test_missing_legacy_outputs_are_inconclusive` and
`test_partial_legacy_outputs_cannot_issue_incomplete_invoice`.

The first exploratory billing probe used an entirely empty response: a deferred
ledger constraint rejected its empty journal, so it did **not** issue a zero
invoice. The retained billing probe omits usage components while keeping a
nonzero daily supply charge, testing output completeness independently of that
ledger safeguard.

### M3-RR-F2 — High: malformed line identity leaves previous approval eligible

Location: `src/taryx/core/migration/legacy_adapter.py:130–142` and
`src/taryx/core/migration/services.py:84–119`.

Line identity fields are copied without type validation. With a previously
approved comparison, a subsequent response whose first line has `element: []`
passes `_parse` but raises `TypeError` when `diff_lines` uses it in a dictionary
key. The error occurs outside the `LegacyFailure` handler, so no INCONCLUSIVE
observation is persisted. The previous success and its decisions remain the
latest evidence and the gate still reports no blockers. Thus a malformed
latest attempt does not fail closed, unlike the already-tested malformed JSON,
nonfinite-number and null-version cases.

Validate line identity and metadata types/domains at the adapter boundary and
translate invalid protocol data into `LegacyFailure("malformed", ...)` before
comparison/persistence. Verify that the failed observation supersedes previous
success for gate purposes. Probe:
`test_invalid_line_identity_supersedes_prior_success`.

## Verification

Environment: existing Python 3.14 virtual environment, local PostgreSQL on
localhost:55432 (real default/shadow roles), subprocess legacy simulator,
existing frontend dependencies. Test HTTP responses for the new failure cases
are injected; persistence, gate evaluation and billing are real application
paths against PostgreSQL.

- HEAD verified before review; initial working tree contained only the
  untracked `docs/project/evidence/m3-events-r1.jsonl` driver log, preserved.
- `UV_CACHE_DIR=/tmp/taryx-review-uv make check`: passed with approved local
  service access. Ruff lint/format, mypy, import contracts (including the
  deliberate violation rejection), **161 backend tests**, **6 frontend tests**,
  TypeScript and Vite build passed.
- Initial sandbox attempts were unavailable due to read-only default uv cache
  and blocked database/socket access. Using a writable cache and approved
  service access resolved these environmental failures.
- Existing five M3 probe files: **17 passed** in the combined run (21.88s).
- `.venv/bin/pytest -q docs/project/evidence/m3_re_review_probes.py`:
  **3 failed** in 2.36s, reproducing M3-RR-F1/F2. Observed assertions:
  `difference != inconclusive`; `issued INV-000001 for 1.21`;
  `TypeError ... unhashable type: list; remaining blockers: []`.
- Probe lint/format and final documentation diff/UTF-8/link checks passed;
  final HEAD remained the candidate SHA. Only review docs/probes/affected
  records were written, alongside the pre-existing driver event log.

Reproduce the independent checks:

```bash
.venv/bin/pytest -q \
  docs/project/evidence/m3_re_review_probes.py \
  docs/project/evidence/m3_review_probes.py \
  docs/project/evidence/m3_followup_probes.py \
  docs/project/evidence/m3_commit_window_probe.py \
  docs/project/evidence/m3_gate_deadlock_probe.py \
  docs/project/evidence/m3_admission_cutover_probe.py
```

The new probes are required-behaviour assertions and intentionally fail on this
candidate. They are not xfailed or rewritten to bless observed failures.

## Review coverage and limits

Inspected legacy protocol mapping/parsing, independent simulator scenarios,
comparison and approval scoping, restricted evidence credentials, gate locking,
admission/rollback serialization, billing integration, and GraphQL/portal
controls. Re-ran prior preserved probes rather than relying on the earlier
reviewer's source-only approval. New findings concern response completeness and
schema validation, not a claimed recurrence of the earlier locking defects.

No fresh interactive browser journey, hosted CI, clean dependency installation,
container rebuild, or deployment/process-kill campaign was performed. Frontend
verification is the existing tests/typecheck/build plus source review; earlier
manual portal evidence remains historical. This is not release-readiness or
production regulatory verification.

---

## Remediation — 2026-11-08 (Devin)

Both findings resolved; the three preserved probes pass and are folded
into `tests/test_migration.py` as regressions.

- **M3-RR-F1 (incomplete output)** — `calculate` now reconciles usage
  completeness against the request: import lines must bill exactly the
  metered kWh across import-direction channels. An empty `lines` array
  or a supply-only response raises `LegacyFailure("malformed")`, which
  `run_comparison` persists as INCONCLUSIVE evidence and the billing
  path rejects before issuance. Export credit is deliberately not
  quantity-reconciled: catalogues legitimately truncate or omit
  feed-in tariffs (the seeded FIT-TRUNC-2003 defect), and that
  divergence is comparison evidence rather than a protocol defect.
- **M3-RR-F2 (malformed line identity)** — `_parse_line` strictly
  validates every protocol field's type: `element`, `tariff_code`,
  `unit`, `basis`, `band`, `tariff_version` must be strings of the
  right shape, `segment` must be exactly two ISO date strings, and
  `lines` itself must be a list. `element: []` and similar malformed
  identities now raise `LegacyFailure("malformed")` inside the parse
  boundary instead of escaping as TypeError during comparison, so the
  attempt persists INCONCLUSIVE and supersedes earlier success.

A terminal outcome was also needed on the billing path: a malformed
authoritative response is deterministic — retrying the same request
reproduces it — so `process_operation` now finishes the operation as
`FAILED` (new status) with the rejection detail rather than leaving it
PENDING for unbounded outbox retries. Transient codes (timeout,
unavailable, legacy_error) keep the existing retry semantics.

Verification: preserved probes `m3_re_review_probes.py` **3 passed**;
all 17 earlier M3 probes pass; migration suite **39 tests** including
the three folded regressions; `make check` green — ruff lint/format,
mypy, 3 import contracts, **164 backend tests**, 6 frontend tests,
TypeScript check and production build.

---

## Round two — interrupted, extended remediation — 2026-11-08 (Devin)

Round 2 died on Codex quota mid-verification (`turn.failed`; session
`01a1ba3e-7224-7dc3-a29f-cec764756ff2` retained). The died turn left a
complete probes file (`m3_re_review_r2_probes.py`) exercising boundary
cases of the round-one fixes — all reproduced real gaps, remediated
before the resumed round:

- **Omitted daily supply** — the round-one completeness check
  reconciled import kWh only; a response billing all usage but dropping
  the supply line still issued a partial invoice ($7.47 vs $8.68).
  `_check_usage_completeness` now also requires supply lines covering
  every distinct record day in the request.
- **`agreement_id: 1e309`** — `int(inf)` raised `OverflowError`, which
  escaped `_parse`'s catch tuple. It is now wrapped as `malformed`
  like every other shape violation.
- **Shadow billing evidence** — a malformed authoritative response
  during `calculate_for_billing` left no comparison evidence, so the
  cutover gate stayed clear after the FAILED operation. The shadow
  path now persists the same INCONCLUSIVE row `run_comparison` writes
  before propagating (extracted into `_persist_inconclusive`).

The R2 probes also verify transient codes (`timeout`, `unavailable`)
keep PENDING/retry semantics — only `malformed` terminates FAILED.
All five round-two probes pass and are folded into
`tests/test_migration.py`; the full suite is green (169 backend,
6 frontend).

## Round two resumed independent verification

Date: 2026-11-08 (UTC). Reviewer: Codex (GPT-6 family; exact variant unavailable).
Reviewed SHA: `64ace7dda5a44ddede4a91f74d54eb85e03bfbe8`. Verdict: **APPROVED** for
M3 / TAR-010–012. No outstanding findings in this review scope.

The earlier round-two runs were interrupted by quota and produced no approval.
This completed review uses the latest candidate explicitly supplied by the user.
`git rev-parse HEAD` matched before and after verification. `git diff --quiet
820d5db..HEAD -- src/taryx/core/migration src/taryx/core/billing
tests/test_migration.py` passed: those paths are byte-identical to remediation
commit `820d5dbbc42dff924de2433b8fbc920ec8ea0829`. Current task/GraphQL wiring
was also inspected for the later policy-selection changes; the legacy failure
adapter remains connected. This is not an independent M4 approval.

### Finding disposition

- **M3-RR-F1 resolved:** missing import output and omitted daily supply are
  rejected before issuance. Import quantity reconciles to the requested usage;
  supply quantity reconciles to the distinct requested record-day count.
  The original empty/partial-output probes and the omitted-supply boundary
  probe pass. Export credit remains comparison evidence, preserving the
  intentionally characterised FIT truncation behaviour rather than requiring
  new/legacy export parity at the protocol boundary.
- **M3-RR-F2 resolved:** malformed line identities are rejected inside the
  parser; `OverflowError` from `agreement_id: 1e309` becomes `malformed`.
  Both original and overflow probes persist INCONCLUSIVE evidence that
  supersedes earlier success and blocks the gate.
- **Round-two SHADOW failure gap resolved:** `calculate_for_billing` invokes
  the shared `_persist_inconclusive` path before propagating `LegacyFailure`
  under SHADOW routing. The probe verifies that a malformed operation finishes
  FAILED, its outbox event is delivered, and cutover is nevertheless rejected
  for inconclusive evidence. The two transient-code probes confirm timeout
  and unavailable leave the operation PENDING and outbox undelivered.

### Checks on this candidate

- `UV_CACHE_DIR=/tmp/taryx-review-uv make check` — **passed**: ruff lint/format,
  mypy, all import contracts plus deliberate-violation rejection,
  **197 backend tests** (98.39s), **6 frontend tests**, TypeScript and Vite build.
  Counts include intervening M4 tests; passing them is not a substitute for M4
  independent review.
- All seven preserved M3 probe files — **25 passed** (24.11s): eight re-review
  probes plus 17 earlier probes, including admission, rollback, deadlock and
  commit-window regressions. No probes were changed or newly added this run.
- Ruff check/format of both re-review probe files — **passed**.
- Final `git diff --check`, UTF-8/local-link checks, M3 task index/status
  consistency, candidate HEAD and allowed-path checks — **passed**.

Reproduce the probe run:

```bash
.venv/bin/pytest -q \
  docs/project/evidence/m3_re_review_probes.py \
  docs/project/evidence/m3_re_review_r2_probes.py \
  docs/project/evidence/m3_review_probes.py \
  docs/project/evidence/m3_followup_probes.py \
  docs/project/evidence/m3_commit_window_probe.py \
  docs/project/evidence/m3_gate_deadlock_probe.py \
  docs/project/evidence/m3_admission_cutover_probe.py
```

Checks used the existing virtual environment and local PostgreSQL/default and
shadow roles, with approved local-service access for simulator sockets. Probe
fault responses are injected while gate/persistence/billing paths use the real
database. No fresh interactive browser journey, clean installation, hosted CI,
container rebuild, deployment or process-kill campaign was performed; earlier
manual portal evidence is retained as history. Approval is scoped to M3 and
these recorded limits, not general release readiness.

Only affected project records were edited. The pre-existing untracked driver
log `docs/project/evidence/m3-events-r2c.jsonl` was preserved. No implementation
changes or commits were made.
