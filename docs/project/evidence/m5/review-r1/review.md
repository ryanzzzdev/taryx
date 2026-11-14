# M5 independent review — round 1

Candidate: `9a2c5ba0237d2d5bce65a5bfdedf32ce0a384f41`.
Verdict: **CHANGES_REQUESTED**. Scope: TAR-016–018.

The supplied SHA is HEAD, a README commit whose ancestry includes the M5
implementation (c4020f0 through e24be08) and subsequent TAR-020 portal work.
Reviewed M5 code/evidence at that exact snapshot; TAR-020 is excluded.
The pre-existing untracked `m5-events-r1.jsonl` was left untouched.

## Findings

### M5-F1 — High: campaign PASS does not enforce financial invariants

`scripts/fault-campaign.py:310–339` records financial counts but the duplicate
scenario's observer returns PASS unconditionally. Other scenarios likewise
omit balance checks; the first two check invoice counts only. The preserved
probe supplies two invoices and an unbalanced journal and still gets PASS.
`scripts/portfolio-run.py:103–105` similarly accepts 100 fast completed operations
with zero linked invoices and an unbalanced journal. Assert all required final
business invariants, wait for duplicate consumers to finish before observing,
and return a failing process exit status if any scenario fails. Existing raw
counts are useful observations, but the harness is not a reliable regression gate.

### M5-F2 — Medium: failed/no-op ingestion can pass the frozen budget gate

`scripts/measure-budgets.py:125–151` ignores the ingest subprocess exit code,
drops failed HTTP probes and compares only successful response timings.
The preserved probe returns ingest exit 1 with `ingestion failed`, yet reports
PASS. Repeated execution also reuses identical input, allowing content-hash
deduplication to substitute for an R1 ingest; portfolio repeats have the same
fixed-file issue. Require successful publication of the full expected interval
count, record request failures, and reset or select fresh periods explicitly.

### M5-F3 — Medium: billing-budget evidence excludes rating and reuses old work

`scripts/portfolio-run.py:123–155` creates operation timestamps only after
`rate_account` finishes; its p95 gate excludes that work. On rerun it performs
no billing at all, reconstructs a batch interval from operation timestamps,
and samples resources during other work. The committed result explicitly
uses this reconstruction and lacks rating timings. It cannot establish the
frozen whole billing-run p95 or current-run billing memory/queue behaviour.
Measure from before rating through completion, run a fresh identified batch,
and retain contemporaneous timing/resource samples. This is a verification
gap, not a claim that the application necessarily exceeds the budget.

### M5-F4 — Medium: installation has no repeatable schema-upgrade migration run

`deploy/k8s/install.sh:34–40` reapplies fixed-name migration Jobs and waits for
Complete. Existing completed Jobs do not execute again; changing their image
also makes their pod template immutable. All workloads use unchanged `latest`
with `IfNotPresent`, so reloading an image and rerunning install does not roll
existing deployments. With a new pending migration, replacement app pods can
wait indefinitely while the script sees the old migration Job as complete.
Provide versioned/recreated migration Jobs and an explicit image/rollout
procedure. Demonstrate a compatible schema upgrade and a failed migration;
the existing fresh install and deliberately broken init command do not test
that upgrade path. This finding is from source inspection, not a live upgrade.

## Checks and limits

- `python3 docs/project/evidence/m5/review-r1/probes.py`: three isolated
  reproductions passed (each confirms a false-positive gate). Output: `probes.txt`.
- Ruff lint/format: passed (126 files). Mypy: passed (110 source files).
- Import contracts: three passed; deliberate forbidden import rejected.
- Existing Compose services and kind pods inspected successfully with elevated
  local access. Temporary unlabeled pod connection to db:5432 timed out as
  expected; pod removed. Runnable procedure: `network-probe.sh`. This checks
  only the db boundary, not every NetworkPolicy path.
- Full backend suite: result recorded in `pytest.txt`.
- No fresh cluster/reset, schema upgrade, whole fault campaign, R1 workload,
  browser journey, hosted CI or Sentry export rerun. Existing evidence was
  inspected, not promoted to independent reproduction. Live image source
  identity was not established, so the network result is environment evidence.
- The seven-scenario “abandoned lease” case stops the consumer before dispatch;
  it demonstrates queued retention, not recovery of an already claimed lease.
  Retain that distinction when extending the campaign.

TAR-016–018 reopened; M5 remains In progress. Fix the gates, rerun the relevant
measured/fault scenarios, and provide upgrade evidence before re-review.
