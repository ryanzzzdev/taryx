# TAR-016 frozen-budget runs — 2026-11-14 02:03 UTC

Reference environment per features/metering-and-rating.md §Measurement profile (14-core, ~30 GiB RAM, Docker/Compose on NVMe).
Probes: `/healthz` issues `SELECT 1`; `/metrics` runs status-count aggregations. SIGKILL recovery is timed from `docker kill` to op
complete via the documented procedure (restart worker + drain outbox).

## r1-ingest-api-p95 — PASS
```json
{
  "scenario": "r1-ingest-api-p95",
  "intervals": 180000,
  "batch_status": "published",
  "batch_selected": 180000,
  "batch_quarantined": 0,
  "ingest_seconds": 30.9,
  "ingest_rc": 0,
  "ingest_tail": "r1.nem12: published (180000 intervals, 180000 selected, 0 quarantined)",
  "request_failures": {
    "healthz": 0,
    "metrics": 0
  },
  "budget": {
    "api_p95_ms": 500,
    "ingest_s": 90
  },
  "healthz": {
    "n": 283,
    "p50_ms": 20.7,
    "p95_ms": 22.9,
    "max_ms": 25.7,
    "baseline_p95_ms": 29.6
  },
  "metrics": {
    "n": 283,
    "p50_ms": 30.5,
    "p95_ms": 34.8,
    "max_ms": 37.0,
    "baseline_p95_ms": 37.5
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
  "op": "budget-kill-1794621820",
  "invoices": 1,
  "unbalanced_journals": 0,
  "result": "PASS"
}
```
