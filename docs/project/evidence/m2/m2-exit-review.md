# M2 exit review — Explainable bills and corrections

Date: 2026-10-25
Scope: TAR-006–TAR-009. Original implementer verdict: criteria satisfied on the evidence below.

Current verdict: the independent re-review of `de0e08d` found four follow-up findings, now remediated and verified (both follow-up probes pass). See [independent review](m2-independent-review.md). Original evidence below is historical.
Suite: `make check` green — 92 pytest tests on real PostgreSQL, ruff,
mypy, three import contracts (plus the deliberate-violation probe),
frontend typecheck/build. Compose stack verified live.

## Itemised calculations match independent references

- tests/test_pricing.py — 12 tests; RC-01 flat $9.13, RC-02 TOU $9.79,
  RC-03 export-credit $8.65, RC-04 boundary $305.47, RC-05 two-day
  $264.77, RC-06 5-minute/DST-day coverage; deterministic replay via
  pinned input digest; explicit errors for incomplete coverage,
  quarantine, missing/overlapping agreements, unknown tariff.
- Live: rate_account ACC-001 2026-03-02 → $8.75 (post-revision data).

## Unique business identities, transactional posting, journal enforcement

- tests/test_billing.py — 11 tests: durable admission with idempotent
  operation IDs and payload-conflict rejection; racing operation IDs
  produce one invoice (uniq_bill_generation); deferred constraint trigger
  rejects unbalanced journals at commit; BEFORE triggers reject UPDATE/
  DELETE on invoices, journals and postings via raw SQL (independent of
  ORM PROTECT); real-subprocess worker kill before commit leaves zero
  financial effect and redelivery produces exactly one.
- Live: INV-000001 via the real Celery worker, Dr 9.23 = Cr 9.23 across
  1100/4000/4100/2100.

## Repeated and successive corrections adjust net recognised liability

- tests/test_corrections.py — 8 tests: RC-09 chain +$0.10 then −$0.07
  computed against recognised (never re-subtracting the original);
  repeated correction returns the same document; zero-delta correction
  persists audit evidence without a journal; superseded-selection runs
  go stale; revert-to-original posts back; racing corrections serialize
  to one generation under the invoice row lock; adjustments immutable at
  the database; subprocess kill mid-correction leaves no effect.
- Live: INV-000001 $8.75 → ADJ-000001 −$0.07 → ADJ-000002 −$0.03 →
  recognised $8.65, issued documents untouched.

## Operator import/bill/explain/correct through the real API

- tests/test_graphql.py — 7 tests: session login/logout and `me`;
  anonymous and role-negative denials (`permission_denied` for viewer
  mutations, operator on approver-only resolve); full ingest → rate →
  bill → poll journey returning the durable operation outcome;
  idempotent retry on the same operation ID; correction journey ending
  in a linked adjustment; audit entries for ingest/rate/bill/resolve;
  approver quarantine resolution; stable rejection codes.
- Live: session + CSRF enforced (rotated-token rejection observed);
  viewer denied mutation while retaining queries; operator billAccount →
  COMPLETE with invoice/adjustment links; portal served at :5174 with
  login, ingest, rate, bill/correct, invoice and quarantine panels.

## Broker interruption leaves admitted work recoverable

- tests/test_billing.py::test_enqueue_failure_leaves_durable_pending_work
  — admission succeeds, dispatch fails, drain_outbox completes it;
  test_outbox_drain_recovers_pending_work; duplicate delivery is a no-op.
- bill_account command and the GraphQL mutation treat enqueue failure as
  pending outbox work; the operation never reports issued state until
  the worker commits.

## Known limitations (not blocking M2)

- GraphQL depth/cost limits are not enforced beyond bounded lists
  (decision 004).
- Correction triggering is operator-driven; automatic scheduling on
  revision arrival is future work.
- Kill-after-commit-before-ack is asserted via the duplicate-delivery
  test rather than a timed kill between commit and ack.
- Portal journeys are exercised through GraphQL contract tests and a
  live curl session; no browser-automation harness exists yet.
