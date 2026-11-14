# M5 independent review — round 3

Candidate: `dee7a7e9d4db328773fb854d28bf08d06b27a8b3`.
Verdict: **APPROVED** for the scoped M5 remediation. M5-F1–F4 are closed.
TAR-016–018 completion is confirmed and M5 is Complete for local portfolio
delivery. TAR-020 remains outside scope. No implementation changes or commit.
The pre-existing untracked `m5-events-r3.jsonl` was preserved.

## Resolution

- **M5-F1 closed:** scenario 2 now waits for drained queues after explicit
  redelivery and before final financial observation. This removes the prior
  reliance on an operation status that was already complete before the kill.
  Existing invariant enforcement and scenario 4's drain remain intact.
- **M5-F2 closed:** both ingest measurement paths parse the submitted command's
  outcome and require `published`, the full expected selected count and zero
  quarantine. They no longer rely on existing database totals. Rejected,
  duplicate, partial, quarantined and unparseable outcomes fail. Budget main
  propagates any failed phase as exit code 1. Existing subprocess and request
  failure checks remain intact. Day generation respects calendar month lengths.
- **M5-F3/F4 remain closed:** whole-run billing timing and repeatable Kubernetes
  upgrades were approved in round two; no relevant regression in this diff.
  The prior independent live upgrade and failure-control-flow evidence is retained.

## Independent checks

| Command | Result | Evidence |
| --- | --- | --- |
| `python3 docs/project/evidence/m5/review-r1/probes.py` | Three corrected checks pass | `probes-r1.txt` |
| `python3 docs/project/evidence/m5/review-r2/probes.py` | 11 tests pass | `probes-r2.txt` |
| `python3 docs/project/evidence/m5/review-r3/probes.py` | Seven additional tests pass | `probes.txt` |
| `uv run --frozen pytest -q` | 234 passed | `pytest.txt` |
| Ruff lint/format, mypy, import contracts | Pass; deliberate forbidden import rejected | `static-checks.txt` |

The new probes cover successful publication as well as failure cases, repeat
measurement checks, and February/April/October interval counts. These are
isolated gate tests with mocked service responses, not real-process campaigns.

## Regenerated evidence inspected

- Fault campaign: seven PASS records; precommit observation has zero invoices,
  postcommit and final billing observations have exactly one and zero unbalanced
  journals; adapter restart ends completed.
- Budget run: 180,000 selected intervals, no quarantine, ingest 30.9 s;
  health/metrics p95 22.9/34.8 ms with zero request failures; kill recovery 6.8 s,
  one invoice, zero unbalanced journals.
- Portfolio: June batch 8.4 s, rate+issue p95 0.470 s, 100 invoice-linked
  operations and zero unbalanced journals. September/October ingest 29.1/30.7 s,
  180,000/186,000 selected, no quarantine. Peak sampled stack memory 6.361 GiB.

Minor non-blocking reporting issue: October's `period` text still says
“30 days”; the generator, selected count and observed workload are correctly
31 days (186,000 intervals). Treat this as a larger-than-R1 ingest; September
provides the exact 30-day repeat. The billing display uses an inclusive-looking
last-day label while execution uses next-month-exclusive date boundaries.

## Limits and disposition

The regenerated real-process campaign/performance results above are implementer
observations reviewed against source and gates. This round did not independently
rerun destructive faults, performance workloads, fresh cluster/reset, or the
browser journey. Round two independently reran the idempotent kind upgrade;
the no-op migration does not establish arbitrary DDL compatibility. Hosted CI,
cloud delivery, live-market conformance and hosted Sentry export remain outside
this approval. Existing recorded revision-ingest performance limitations remain;
no budget or scope change is accepted by this review. Retained resource evidence
is aggregate sampling, not a claim of continuous peak measurement.

No open blocking findings remain for this review unit. Records updated to
confirm TAR-016–018 Done and M5 Complete, preserving prior review history.
