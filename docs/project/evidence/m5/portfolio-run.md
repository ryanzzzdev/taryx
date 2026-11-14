# TAR-018 portfolio measurement — 2026-11-14 01:52 UTC

## r1-billing-batch — PASS
```json
{
  "scenario": "r1-billing-batch",
  "accounts": 100,
  "period": "2026-04-01..2026-04-30",
  "batch_wall_s": 9.1,
  "whole_run_s": {
    "n": 100,
    "p50": 0.276,
    "p95": 0.554,
    "max": 0.626
  },
  "rate_seconds": {
    "p50": 0.07,
    "p95": 0.154,
    "max": 0.199
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

## r1-ingest-repeat-m05 — PASS
```json
{
  "scenario": "r1-ingest-repeat-m05",
  "period": "2026-05 (30 days)",
  "wall_s": 30.3,
  "tail": "r1-m05.nem12: published (180000 intervals, 180000 selected, 0 quarantined)",
  "result": "PASS"
}
```

## r1-ingest-repeat-m06 — PASS
```json
{
  "scenario": "r1-ingest-repeat-m06",
  "period": "2026-06 (30 days)",
  "wall_s": 31.1,
  "tail": "r1-m06.nem12: published (180000 intervals, 180000 selected, 0 quarantined)",
  "result": "PASS"
}
```

## resource-observation — PASS
```json
{
  "scenario": "resource-observation",
  "peak_stack_gib": 6.316,
  "max_queue_depth": 0,
  "samples": 13,
  "budget": {
    "stack_gib": 8.0
  },
  "result": "PASS"
}
```

### Queue depth samples (broker `celery` queue, 3 s cadence)

`[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]`

### Stack memory samples (docker stats GiB, 3 s cadence)

`[5.484, 5.45, 5.539, 5.804, 6.059, 6.316, 6.28, 5.514, 5.807, 5.982, 6.236, 6.226, 5.288]`
