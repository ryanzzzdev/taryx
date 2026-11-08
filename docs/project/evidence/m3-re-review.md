# M3 independent re-review

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
