# M1 metering independent review

Current verdict: **APPROVED** at `e8fda0ccfb83c7ddd976771b0166eb5d8beb7ec5` (round 2, 2026-11-08 UTC). M1-F1–F4 resolved; see the round-two addendum below.

## Historical round-one review

Verdict: **CHANGES_REQUESTED**. Review date: 2026-11-08 UTC.

Requested candidate: `230dc0f2d46b25c02f94f1c0b2d0f5a3a22f5f78` (not a local Git object).
Actual reviewed HEAD: `230dc0f1078243e3448ecc145c842228b22cca8c`, as authorised by “verify HEAD if different”. Do not treat this as verification of the unavailable candidate. Correct the driver candidate before another round.

Scope: TAR-003–006, workspace, frozen metering profile, ingestion/history/quarantine and deterministic itemised rating. The previously approved user-labelled foundation/billing review remains separate and was not re-reviewed. The standard regression suite may exercise those components without granting a new scope approval. Existing `m1c-events-r1.jsonl` and `m1c-session-bootstrap.md` were present before this review and left alone.

## Findings

### M1-F1 — High: repeated channel metadata corrupts interval timestamps

Location: `src/taryx/core/metering/nem12.py:198` and `src/taryx/core/metering/ingestion.py:125`.

Each 200 block overwrites the metadata dictionary entry for its NMI/suffix, while previous parsed days remain. Publication resolves only the final metadata and computes every interval timestamp using the configured channel length. A file containing 288 five-minute readings for March 2 followed by a 30-minute block for March 3 on the same E1 channel is published to a configured 30-minute channel. The first day's readings are spread over six days, introducing false overlaps/conflicts and incorrect date attribution. Validate metadata consistency across repeated channel blocks, or retain and validate metadata per block, before publishing anything.

Probe: `test_mixed_interval_metadata_is_rejected_atomically` fails because status is `published` instead of `rejected`.

### M1-F2 — Medium: repeated channel/day escapes as IntegrityError

Location: `src/taryx/core/metering/nem12.py:201` and `src/taryx/core/metering/ingestion.py:138`.

Date ordering resets at each 200 block. Two otherwise valid blocks for the same channel/day pass parsing and then violate `uniq_record_position` in bulk insertion. The exception escapes ingestion instead of returning an inspectable rejected batch with a stable error code. The transaction rolls back, so this is an explicit-outcome/history failure rather than partial publication. Detect repeated interval identities across blocks before inserting, and retain the rejection outcome.

Probe: `test_repeated_channel_day_has_explicit_outcome` fails with the database unique-constraint exception.

### M1-F3 — Medium: re-enveloped identical revisions change selection versions

Location: `src/taryx/core/metering/selection.py:26` and `src/taryx/core/metering/ingestion.py:252`.

Changing only the 100-header sender makes the content hash different. The same 48 interval revisions then become new winners because the tie-break favours the newest database batch id. Every current source pointer changes and selection_version advances from 1 to 2 despite unchanged value, quality and source timestamps. The rating digest also incorporates those source IDs, so a repeated revision unnecessarily invalidates calculations. This violates the frozen “repeated revisions are no-ops” contract. Retain batch provenance without replacing an equivalent effective selection.

Probe: `test_identical_revision_in_new_envelope_is_selection_noop` fails on all selection identities/versions.

### M1-F4 — High: rating validates different data from its captured snapshot

Location: `src/taryx/core/pricing/services.py:221-225`.

`rate_account` gathers rows before separately querying coverage, without holding the input lock or a consistent transaction snapshot across the reads. When ingestion finishes between those reads, coverage reports 48/48 while the captured list is empty. Rating succeeds and persists only the daily supply charge (1.21 including GST), instead of the correct 9.13 for 24 kWh plus supply. This finding concerns the rating artifact; it makes no claim that previously reviewed issuance bypasses its own stale-input check. Validate coverage from the same snapshot consumed by calculation, with a coherent read/locking strategy for intervals and quarantines.

Probe: `test_rating_never_accepts_empty_snapshot_after_coverage_arrives` deterministically inserts publication between the reads; the accepted run has zero import quantity. This is an interleaving simulation, not a process-level concurrency stress test.

## Reproduction and verification

Run from repository root using the locked environment and local PostgreSQL at port 55432:

```sh
UV_CACHE_DIR=/tmp/taryx-review-uv uv run --frozen pytest -q tests/test_pricing.py tests/test_metering_ingestion.py tests/test_nem12_parser.py
UV_CACHE_DIR=/tmp/taryx-review-uv uv run --frozen pytest -q docs/project/evidence/test_m1_metering_review.py
UV_CACHE_DIR=/tmp/taryx-review-uv make check
```

- Existing scoped suite: **64 passed** (21.96 s). Includes parser, selection/quarantine, revision and independent rating-reference regressions.
- Independent probes: **4 failed, 1 passed** (2.47 s); the four failures reproduce M1-F1–F4. The ordinary flat replay control expects 9.13: 24 × 0.30 = 7.20 plus 0.72 GST; supply 1.10 plus 0.11 GST. An initial probe typo expected 9.02; corrected before the final run and not counted as a product defect.
- Initial sandboxed database attempt could not connect; scoped execution with local database access succeeded. Pure parser check: **22 passed**.
- Full standard check: **passed**; ruff lint/format, mypy, 3 import contracts with deliberate violation rejected, 155 backend tests (88.60 s), 6 frontend tests, TypeScript check and production build.
- Earlier metering review probes: `UV_CACHE_DIR=/tmp/taryx-review-uv uv run --frozen pytest -q docs/project/evidence/m1_review_probes.py` — **10 passed** (2.49 s).
- Final record checks: `git diff --check`, changed-document local file links, strict UTF-8/status icons and unchanged HEAD checks passed.

Limits: no fresh dependency installation/clean Compose rebuild, hosted CI, R1 performance campaign or browser/broker fault exercise in this round. Sourced-profile references were inspected in repository records; authoritative external documents were not independently revalidated. Existing catalogue/reference arithmetic and local runtime checks do not establish production regulatory conformance. The unavailable supplied full SHA remains an identity gap.

## Closeout

TAR-005 and TAR-006 reopened; M1 is In progress for this review scope. TAR-003/TAR-004 unchanged. Billing approval and its prior evidence remain intact. Fix M1-F1–F4, preserve/fold these probes into the suite, and request re-review at an accurate full commit SHA. No implementation changes or commits made by the reviewer.

---

## Remediation — 2026-11-08 (Devin)

All four findings resolved at the remediation commit; the five preserved
probes pass and each defect case is folded into `tests/` as a regression.

- **M1-F1** — `parse_nem12` now retains per-channel metadata across
  repeated `200` blocks and rejects the file with `conflicting_200` when
  a repeated block declares different metadata (interval length, UOM,
  serial). Days parsed under one block's interval length can no longer
  be re-timed by a later block. Regression:
  `test_mixed_interval_metadata_rejected_atomically` in
  `tests/test_metering_ingestion.py`.
- **M1-F2** — the parser tracks seen `(nmi, suffix, interval_date)`
  triples across blocks; a repeated channel/day raises `repeated_interval`
  and the batch lands as an inspectable `REJECTED` row instead of
  leaking an `IntegrityError` from `uniq_record_position`. Regression:
  `test_repeated_channel_day_is_explicit_rejection`.
- **M1-F3** — `_publish_interval` compares the precedence tuple
  `(quality rank, MSATS timestamp, update timestamp)` plus value/quality
  of the winning record against the incumbent; an identical record in a
  new file envelope keeps the original `source_record` and
  `selection_version`, so repeated revisions leave rating digests
  untouched. Regression:
  `test_identical_revision_in_new_envelope_is_selection_noop`.
- **M1-F4** — `rate_account` validates coverage against the same
  captured snapshot consumed by calculation (`len(rows)` vs the
  expected interval count, plus open quarantines from the gathered
  list) instead of re-querying the database. A publication interleaved
  after the gather can no longer make an empty snapshot validate; the
  run either consumes a coherent 48-record snapshot or raises
  `incomplete_coverage`. Regression:
  `test_rating_coverage_uses_the_consumed_snapshot` in
  `tests/test_pricing.py`.

Verification: preserved probes `test_m1_metering_review.py` **5
passed**; earlier `m1_review_probes.py` 10 passed; scoped suite 68
metering/pricing/parser tests; `make check` green — ruff lint/format,
mypy, 3 import contracts, **159 backend tests**, 6 frontend tests,
TypeScript check and production build.

The round-1 prompt carried a mistyped candidate SHA; the reviewer
verified and reported against the actual HEAD
(`230dc0f1078243e3448ecc145c842228b22cca8c`) and flagged the gap — the
round was accepted on the real reviewed SHA.

## Independent round-two review — 2026-11-08

Candidate and verified HEAD: `e8fda0ccfb83c7ddd976771b0166eb5d8beb7ec5`.
The round-one identity gap is resolved for this round. Initial working tree contained only the unrelated untracked `m1c-events-r2.jsonl`, preserved unchanged by the reviewer.

Code review confirms:

- **M1-F1 resolved:** repeated metadata is compared before replacing the channel dictionary entry. The preserved corruption probe rejects atomically; the folded regression also checks `conflicting_200`.
- **M1-F2 resolved:** seen channel/day identities span 200 blocks, yielding `repeated_interval` before publication. The folded test verifies the error code and absence of records.
- **M1-F3 resolved:** equivalent value, quality and precedence retain the incumbent source and selection version. Additional boundary coverage checks the rating digest remains stable and a genuinely newer timestamp still advances the version.
- **M1-F4 resolved:** coverage uses the captured interval rows and quarantine list consumed by rating. The preserved interleaving probe now rejects the empty snapshot. This establishes the reported coverage fix, not a general serializable snapshot guarantee across all concurrent metadata writers.

Two additional probes in `test_m1_metering_review.py` exercise valid repeated blocks on distinct days and equivalent-versus-newer revision digest/version behaviour. No new implementation finding arose from this review.

Documentation precision: the implementer's addendum above mentions serial changes, but `ChannelMeta` does not include the meter serial; the new comparison covers configuration, suffix, unit and interval length. Serial validation was not part of M1-F1. Four defect probes were newly folded into `tests/`; the fifth preserved probe is a replay control already covered by existing pricing tests.

Verification results and final verdict follow below. Historical round-one failures remain preserved above. Existing clean-install, hosted CI, performance, browser/broker and external-source verification limits are unchanged; this review does not revisit billing approval or grant deployment/regulatory readiness.

### Round-two verdict and verification

**APPROVED** for the requested TAR-003–006 metering/rating scope at `e8fda0ccfb83c7ddd976771b0166eb5d8beb7ec5`. All four findings are resolved.

- `UV_CACHE_DIR=/tmp/taryx-review-uv make check`: passed; 159 backend tests (85.19 s), 6 frontend tests, lint/format, mypy, import contracts with deliberate violation rejection, TypeScript and build.
- `UV_CACHE_DIR=/tmp/taryx-review-uv uv run --frozen pytest -q docs/project/evidence/test_m1_metering_review.py docs/project/evidence/m1_review_probes.py`: **17 passed** (4.36 s): five original, two additional and ten earlier metering probes.
- Probe ruff lint/format checks passed. Changed-record UTF-8/local-link checks, `git diff --check` and unchanged HEAD verification passed.

TAR-005/TAR-006 completion and M1 completion confirmed. Prior billing approval retained. Only review evidence, probes and affected records changed; no commit made.
