# Independent M1 exit review

Reviewed commit: `b5a180f` (clean working tree before review).
Date: 2026-10-25
Verdict: M1 reopened; TAR-003 remains Done, TAR-004 Ready for profile correction, TAR-005 Backlog pending the corrected profile and remediation below. No application code changed by this review.

## Verification

- `make check`: PASS. Ruff lint/format, mypy, three import contracts and deliberate forbidden-import probe, all 21 existing PostgreSQL tests, frontend typecheck/build.
- Existing Compose stack: API/web/worker running; PostgreSQL 18.6 and RabbitMQ 4.3.7 healthy. No fresh image rebuild, hosted CI or performance campaign performed.
- Additional probes use real PostgreSQL via pytest's temporary test database, separate thread connections and controlled interleavings. No seeded application database reset was performed.
- Run from repository root: `uv run pytest docs/project/evidence/m1_review_probes.py -c pyproject.toml -q -p no:cacheprovider --tb=short`.
- Observed on reviewed code: **10 failing probes**, covering the five findings below. These are preserved regression targets, not successful acceptance tests. Fixture fields were modified independently to check documented edge cases. They are outside the normal `tests/` collection until fixes incorporate suitable regressions.
- Initial direct `.venv/bin/python -m pytest` invocation yielded 20 passes and a missing `lint-imports` PATH error. The documented `make check` activates the correct uv environment and passes; that initial invocation is not a product defect.

## Findings

### R1 — P1: Parse actual NEM12 quality methods and interval-event ranges

Location: `src/taryx/core/metering/nem12.py:165–170,193–214`.

The parser accepts only bare quality letters and interprets 400 records as one interval plus timestamps. The cited AEMO MDFF v2.7 specifies a quality/method combination such as E52 and 400 records carrying start/end interval ranges. The review's standard E52 input fails with `bad_quality`; a six-field ranged 400 record fails with `malformed_400`. The generated fixtures implement the same incorrect format as the parser, so the existing V-quality test cannot catch this.

Correct the frozen profile, parser and fixtures together; retain method metadata and inherit the appropriate 300-record timestamps. Verify legal range coverage, gaps, overlaps and mandatory reason information against independently sourced examples. TAR-004/005 and BLK-001 reopened.

Primary source: [AEMO MDFF v2.7](https://aemo.com.au/-/media/files/electricity/nem/retail_and_metering/market_settlement_and_transfer_solutions/2025/mdff-specification-nem12-nem13-v27.pdf), sections 4.4–4.5.

### R2 — P1: Serialize candidate selection and current-reading publication

Location: `src/taryx/core/metering/ingestion.py:144–174`.

Two different batches can select candidates before seeing each other's uncommitted revisions, then overwrite the same CurrentInterval with stale results. There is no lock covering candidate selection through publication. A controlled run lets the older 0.6 revision select first, commits the newer 0.8 revision, then resumes the older publisher. Final current values contain both 0.6 and 0.8 although the newest revision is 0.8 for every interval. The transaction wrapper does not prevent this lost-update race.

Serialize affected channel/interval updates in deterministic lock order, including first-publication cases, or use a retry/version protocol that re-evaluates candidates under contention. Include simultaneous higher-precedence and conflicting revisions in real database tests. TAR-005 must pass before rating depends on current readings.

### R3 — P2: Recover duplicate insertion outside the failed transaction/savepoint

Location: `src/taryx/core/metering/ingestion.py:67–83`.

When two identical batches pass the preflight hash lookup, one loses the unique insert race. Its IntegrityError is caught inside the same atomic block and the handler immediately queries using the now-broken transaction. Observed outcomes are `published` and `TransactionManagementError`, rather than `published` and `duplicate`.

Use an inner savepoint or catch outside the failed transaction before querying the winning batch. Reconcile rejected-original races as well: the uniqueness rule includes rejected rows, while the handler looks up only published rows. TAR-005.

### R4 — P2: Reject invalid interval values and malformed input before publication

Location: `src/taryx/core/metering/nem12.py:149–179` and ingestion's error boundary.

Decimal construction accepts `-0.5`, `NaN`, `Infinity` and `1e2`; all four pass the parser. The supported format forbids negative/exponential interval values and non-finite values cannot form meaningful meter quantities. A truncated `300` row also escapes as IndexError rather than the documented Nem12Error/rejected-batch outcome. Invalid encoding likewise needs deliberate handling at the byte boundary.

Validate lexical form, finiteness, supported precision/range and row shape before accessing fields or writing records. Enforce mandatory metadata and retain stable rejection outcomes for malformed batches. Exercise both pure parser and ingestion rejection paths. TAR-005.

### R5 — P2: Retire obsolete quarantine when a later revision resolves the conflict

Location: `src/taryx/core/metering/ingestion.py:150–183`.

After two equal-precedence values conflict, a strictly later unambiguous revision updates CurrentInterval but leaves the old quarantine Open. The review observes expected=48, selected=48, quarantined=1 and complete=False even after the newer data wins. No resolution service exists. This permanently prevents the planned billing coverage gate from admitting the period.

When selection establishes an unambiguous newer winner, resolve the obsolete conflict with retained history, or provide an explicit supported review resolution path. Ensure current conflicts still block and store all relevant competing records for investigation. TAR-005.

## Exit impact and next action

The skeleton checks pass, but the sourced-format and deterministic-ingestion exits fail. Correct TAR-004's format profile, remediate TAR-005, add independent-format and concurrency regressions, then rerun the existing suite and these probes before restoring M1 Complete. BLK-003 measurement budgets are not reopened by this review; their later performance acceptance remains untested.

## Remediation outcome (2026-10-25)

All five findings remediated in the checkpoint following this review; the preserved probes now pass 10/10 and are folded into `tests/` as maintained regressions.

- R1: parser implements MDFF v2.7 `QMM` QualityMethod (method codes retained as `method_code`) and ranged 400 records tiling the whole day, inheriting 300 timestamps. Frozen profile and fixtures corrected; new fixtures cover `E52`, ranged/mixed-method 400s and reason codes.
- R2: two-phase optimistic publication — unlocked candidate read, then per-interval locked re-evaluation in deterministic order with insert-collision retry. Concurrent publishers cannot regress current selection.
- R3: duplicate-hash insert loss is contained in a savepoint; the loser resolves the real non-duplicate original whether published or rejected.
- R4: lexical interval-value validation (non-negative plain decimal), row-shape guards before field access, `S`/`F` reason-code enforcement and a deliberate UTF-8 byte-boundary rejection.
- R5: an unambiguous newer winner resolves the open quarantine (resolved status + timestamp, all top-precedence rivals retained on the record); open quarantines still block coverage.

Verification: `uv run pytest docs/project/evidence/m1_review_probes.py` → 10 passed; `pytest` → 54 passed on real PostgreSQL; ruff/mypy/import contracts clean; live Compose ingest verified for ranged 400s, encoding, value and range rejections. The remaining 400-filed `ReasonDescription` is parsed but not yet stored (metadata is recorded at flag/method/reason level only).

## Independent confirmation at 2a46650

2026-10-25: Saved M1 probes pass 10/10 and the full documented suite passes 92 tests plus lint/types/import/frontend checks. The five original M1 findings are resolved; M1 remains Complete. M2 has separate findings in [the independent review](m2-independent-review.md). No new M1 performance or clean-install claim is made.
