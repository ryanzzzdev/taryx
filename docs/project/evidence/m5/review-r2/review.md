# M5 independent review — round 2

Candidate: `1c7e61d308a6961d9107ca4ba099f15548188682`.
Verdict: **CHANGES_REQUESTED**. Scope: remediation of M5-F1–F4, TAR-016–018.
TAR-020 remains outside scope. Pre-existing untracked `m5-events-r2.jsonl`
was left untouched. No implementation changes or commit made.

## Findings carried forward

### M5-F1 — Medium, partially resolved: post-commit redelivery is observed too early

`scripts/fault-campaign.py:254–267` dispatches a duplicate after restarting
but waits only for the operation to be `complete`. That status was already
committed before the kill, so this wait can return before either redelivery
has run. The subsequent invoice count cannot establish “explicit redelivery
added nothing.” Unlike scenario 4, scenario 2 never calls `wait_queue_drained`.
Wait for the dispatched/redelivered tasks to finish before final financial
observation (or prove task-specific completion). The independent regression
probe detects this missing wait. This is a remaining evidence race, not a
reproduced duplicate billing defect.

Resolved portions: financial count/balance checks now reject bad results;
scenario 4 waits for queue drain; campaign main returns failure on failed
scenarios. The original three remediation probes pass, and an expanded probe
exercises scenario 4 itself, rather than only its helper. Saved campaign
results report seven passes with valid observed financial counts.

### M5-F2 — Medium, partially resolved: publication and process-exit gates remain false-positive

`scripts/measure-budgets.py:132–163` compares the *entire database's* current
interval count with 180,000. It never verifies the submitted batch's status,
record/selected/quarantine counts or workload identity. The real
`ingest_nem12` management command prints rejected/duplicate outcomes and
returns normally, so checking its exit code does not close this gap. On an
already populated estate a rejected, duplicate, or wholly quarantined batch
can still report PASS. Three independent probes reproduce those cases with
540,192 existing intervals. `scripts/portfolio-run.py:245–257` also gates
repeat ingests on time alone, accepting these successful-command outcomes.

Additionally, `measure-budgets.py:208–241` writes FAIL records but returns
None, making `sys.exit(main())` exit zero. A fourth probe proves this.
Require batch-specific successful publication/selection with no quarantine,
reject deduplication for timed ingest runs, and propagate any failed phase
to a nonzero process exit. Default run timestamps reduce accidental dedupe;
they do not replace checking the outcome, especially with `R1_STAMP` overrides.

Resolved portions: nonzero ingest exit and dropped HTTP probes now fail the
phase. Both independently tested. The committed rerun itself reports a
published full batch and no request failures; these findings challenge the
reusable gate, not that recorded observation.

## Closed findings

- **M5-F3 resolved:** rating durations are added to ordered per-operation
  completion durations, the batch starts before rating, and an already
  completed tag fails instead of reconstructing historical timing. Expanded
  probes confirm slow rating breaches the budget and old tags are refused.
  Saved fresh-run evidence reports whole-run p95 0.554 s, 100 invoice-linked
  operations and zero unbalanced journals. Resource samples are collected
  while phases execute; phase labels are not retained in emitted evidence,
  so the saved aggregate memory list alone cannot identify phase peaks.
- **M5-F4 resolved:** fixed-name Jobs are explicitly deleted/recreated and
  `--rollout` restarts all four deployments after successful Job waits. The
  reviewer reran `bash deploy/k8s/install.sh --rollout` successfully against
  the existing kind cluster. Jobs completed, all four deployments rolled,
  and all four app image IDs match
  `sha256:e2184fc140f94b2952de910e4d3a70579ea7c5b7d71dafd56c5c051d8473b45e`.
  `audit/0002_upgrade_boundary_probe` is applied. A mocked kubectl failure
  confirms failed migration wait exits before rollout restart. This round
  reran an idempotent upgrade; the pending-migration application is the
  implementer's retained evidence. The probe migration is a no-op SQL step,
  not evidence of arbitrary DDL compatibility.

## Verification

| Check | Result | Evidence |
| --- | --- | --- |
| `python3 docs/project/evidence/m5/review-r1/probes.py` | All three corrected checks pass | `original-probes.txt` |
| `python3 docs/project/evidence/m5/review-r2/probes.py` | 11 tests: 6 pass, 5 fail for residual F1/F2 | `probes.txt` |
| `python3 docs/project/evidence/m5/review-r2/upgrade-gate-probe.py` | Pass; mocked failed migration blocks restart | `upgrade-gate-probe.txt` |
| `bash deploy/k8s/install.sh --rollout` | Pass on existing kind cluster | `upgrade.txt` |
| `uv run --frozen pytest -q` | 234 passed | `pytest.txt` |
| Ruff check/format, mypy, import contracts | Pass; deliberate forbidden import rejected | `static-checks.txt` |
| `bash -n deploy/k8s/install.sh` | Pass | Command run locally |

No fresh cluster reset, destructive Compose fault campaign, R1 performance
campaign, browser journey, hosted CI or Sentry export was independently rerun
this round. Reviewed committed campaign/budget/portfolio evidence separately
from independent reproductions. Image IDs match each other; their full source
identity was not independently attested. Earlier review limits remain.

TAR-017 completion is confirmed for the scoped delivery remediation; TAR-016
and TAR-018 remain In progress for F1/F2. M5 remains In progress. Fix these
remaining gates and rerun affected evidence before the next review.
