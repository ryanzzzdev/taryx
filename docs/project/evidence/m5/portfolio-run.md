# TAR-018 portfolio measurement — 2026-11-14 02:04 UTC

## r1-billing-batch — PASS
```json
{
  "scenario": "r1-billing-batch",
  "accounts": 100,
  "period": "2026-06-01..2026-06-30",
  "batch_wall_s": 8.4,
  "whole_run_s": {
    "n": 100,
    "p50": 0.254,
    "p95": 0.47,
    "max": 0.502
  },
  "rate_seconds": {
    "p50": 0.069,
    "p95": 0.133,
    "max": 0.181
  },
  "invoices": 100,
  "unbalanced_journals": 0,
  "budget": {
    "per_account_p95_s": 2.0,
    "batch_s": 300
  },
  "result": "PASS"
}
```

## r1-ingest-repeat-m09 — PASS
```json
{
  "scenario": "r1-ingest-repeat-m09",
  "period": "2026-09 (30 days)",
  "wall_s": 29.1,
  "batch_status": "published",
  "batch_selected": 180000,
  "batch_quarantined": 0,
  "tail": "r1-m09.nem12: published (180000 intervals, 180000 selected, 0 quarantined)",
  "result": "PASS"
}
```

## r1-ingest-repeat-m10 — PASS
```json
{
  "scenario": "r1-ingest-repeat-m10",
  "period": "2026-10 (30 days)",
  "wall_s": 30.7,
  "batch_status": "published",
  "batch_selected": 186000,
  "batch_quarantined": 0,
  "tail": "r1-m10.nem12: published (186000 intervals, 186000 selected, 0 quarantined)",
  "result": "PASS"
}
```

## resource-observation — PASS
```json
{
  "scenario": "resource-observation",
  "peak_stack_gib": 6.361,
  "max_queue_depth": 0,
  "samples": 12,
  "budget": {
    "stack_gib": 8.0
  },
  "result": "PASS"
}
```

### Queue depth samples (broker `celery` queue, 3 s cadence)

`[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]`

### Stack memory samples (docker stats GiB, 3 s cadence)

`[5.357, 5.397, 5.579, 5.875, 6.007, 6.317, 6.191, 5.606, 5.934, 6.044, 6.361, 6.309]`
