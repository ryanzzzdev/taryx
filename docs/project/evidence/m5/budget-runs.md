# TAR-016 frozen-budget runs — 2026-11-13 12:30 UTC

Reference environment per features/metering-and-rating.md §Measurement profile (14-core, ~30 GiB RAM, Docker/Compose on NVMe).
Probes: `/healthz` issues `SELECT 1`; `/metrics` runs status-count aggregations. SIGKILL recovery is timed from `docker kill` to op
complete via the documented procedure (restart worker + drain outbox).

## r1-ingest-api-p95 — PASS
```json
{
  "scenario": "r1-ingest-api-p95",
  "intervals": 180000,
  "ingest_seconds": 32.9,
  "ingest_tail": "r1.nem12: published (180000 intervals, 180000 selected, 0 quarantined)",
  "budget": {
    "api_p95_ms": 500,
    "ingest_s": 90
  },
  "healthz": {
    "n": 306,
    "p50_ms": 20.5,
    "p95_ms": 23.1,
    "max_ms": 26.5,
    "baseline_p95_ms": 64.5
  },
  "metrics": {
    "n": 306,
    "p50_ms": 29.9,
    "p95_ms": 34.7,
    "max_ms": 38.8,
    "baseline_p95_ms": 31.9
  },
  "result": "PASS"
}
```

## sigkill-recovery-budget — PASS
```json
{
  "scenario": "sigkill-recovery-budget",
  "kill_to_complete_s": 6.8,
  "budget_s": 60,
  "op": "budget-kill",
  "invoices": 1,
  "unbalanced_journals": 0,
  "result": "PASS"
}
```
