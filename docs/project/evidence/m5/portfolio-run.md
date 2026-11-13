# TAR-018 portfolio measurement — 2026-11-13 14:13 UTC

## r1-billing-batch — PASS
```json
{
  "scenario": "r1-billing-batch",
  "accounts": 100,
  "period": "2026-04-01..2026-05-01 (30 days)",
  "batch_wall_s": 8.3,
  "op_latency_s": {
    "n": 100,
    "p50": 0.2,
    "p95": 0.386,
    "max": 0.477
  },
  "invoices": 100,
  "unbalanced_journals": 0,
  "budget": {
    "per_account_p95_s": 2.0,
    "batch_s": 300
  },
  "result": "PASS",
  "note": "reconstructed from persisted op timestamps (prior run)"
}
```

## r1-ingest-repeat-may — PASS
```json
{
  "scenario": "r1-ingest-repeat-may",
  "period": "2026-05 (30 days, fresh)",
  "wall_s": 48.2,
  "tail": "r1-may.nem12: published (180000 intervals, 180000 selected, 0 quarantined)",
  "result": "PASS"
}
```

## r1-ingest-repeat-june — PASS
```json
{
  "scenario": "r1-ingest-repeat-june",
  "period": "2026-06 (30 days, fresh)",
  "wall_s": 51.4,
  "tail": "r1-june.nem12: published (180000 intervals, 180000 selected, 0 quarantined)",
  "result": "PASS"
}
```

## resource-observation — PASS
```json
{
  "scenario": "resource-observation",
  "peak_stack_gib": 5.764,
  "max_queue_depth": 0,
  "samples": 16,
  "budget": {
    "stack_gib": 8.0
  },
  "result": "PASS"
}
```

### Queue depth samples (broker `celery` queue, 3 s cadence)

`[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]`

### Stack memory samples (docker stats GiB, 3 s cadence)

`[4.761, 5.025, 5.266, 5.347, 5.486, 5.677, 5.764, 5.652, 5.02, 5.196, 5.237, 5.368, 5.498, 5.675, 5.672, 5.629]`

## Known gap — same-day mass revision (measured, not budgeted)

Two earlier runs on 2026-11-13 measured a full-estate *revision* ingest —
same April days, new values, later load/update stamps (the genuine
revision path: every CurrentInterval takes the update branch):

- `r1-ingest-revision-0.6`: **445.5 s** wall
- `r1-ingest-revision-0.7`: **458.9 s** wall
- peak stack memory during revision: **7.26 GiB**

This path is over the 90 s budget: revision updates run one
CASE-per-column UPDATE per 2000-row chunk (~90 statements) plus the
double candidate fetch (~360k rows). Whole-estate same-day revision
files are outside the declared R1 workload (fresh monthly deliveries),
but the gap is recorded honestly: bulk revision at this scale needs a
different write path (e.g. staging-table merge or partition swap) if it
becomes a real requirement.

A second recorded finding from these runs: equal-precedence revision
files (same load/update stamp as the originals) are correctly
quarantined per interval — a file that only changes values without
bumping the load/update stamps produces 180k quarantined intervals,
which is correct domain behaviour but a pathological operational shape.
