# M4 independent review — authorised round 5

Candidate: `98fad76c78bb463200116ab3fc6bf0f20f3458bc`.
Verdict: **APPROVED** for the reviewed remediation. No new correctness findings.

## Resolution

**M4-F8 resolved.** The core consumer updates only the row whose current state
is pending and whose pending correlation matches the envelope. A stale Python
instance cannot authorize an update of a newer transfer. The no-update path
checks current registration for idempotent replay. Clearing also requires the
matching pending correlation; admission writes state and correlation together.

The rewritten round-4 probe correctly isolates the stale-read scenario. Its
previous nested-drain shape could roll the simulated competitor back with the
rejected delivery, so it was not an independent-transaction reproduction.
The preserved round-3 interleaving and rewritten round-4 probe both pass.
New round-5 probes exercise old rejection and HTTP-conflict failure after new
admission, clearing through a stale nonpending instance, matching replay and
clearing after registration. All preserve the intended database state.

**Live freshness gap resolved.** All four app containers report image
`sha256:0e92fe3ff66a5ee97081931e1cf427d0bd7e96ac4706aae030fb973017b29d0c`.
Both imported `accounts.services` and `market.services` have ASTs equivalent to
the candidate checkout in each container, including the atomic consumer and
at-cap submission failure handling. This is module-level verification, not a
claim that every file in the image has been compared.

## Reproduction and results

Run the database suites serially from the repository root:

```sh
UV_CACHE_DIR=/tmp/taryx-uv-cache uv run pytest -q docs/project/evidence/m4-probes
UV_CACHE_DIR=/tmp/taryx-uv-cache make check
UV_CACHE_DIR=/tmp/taryx-uv-cache uv run python docs/project/evidence/m4-probes/check_live_source.py
```

- Preserved probes: **28 passed** ([output](m4-probes-r5.txt)).
- Expanded probes: **31 passed** ([output](m4-probes-r5-expanded.txt));
  [new runnable cases](m4-probes/test_m4_round5.py).
- Live image/import comparison: **passed** ([output](m4-live-source-r5.txt));
  [runnable read-only checker](m4-probes/check_live_source.py).
- `make check`: **passed**, 222 backend and 6 frontend tests, lint/format,
  mypy, import contracts including the intentional negative probe, frontend
  typecheck and production build ([output](m4-check-r5.txt)).
- New probe lint/format, record UTF-8/status consistency and `git diff --check`: passed.

## Scope and remaining evidence

PostgreSQL tests and deterministic interleavings establish the reported
regressions; they are not a live multi-worker stress or process-kill campaign.
Live isolation probes remain green. No fresh-volume bootstrap, live
kill/restart, billing-under-market-outage, browser journey, hosted CI or
real-market conformance campaign was performed in this round. Broker bootstrap
coverage remains model-based. M3 approval is unchanged.

TAR-013's outstanding candidate-image verification is closed. TAR-015 and M4
retain In progress pending explicit exit evidence for unrelated billing during
market outage and live adapter restart, or an accepted scope allocation to
TAR-016. This is a verification limitation, not a new code defect or a rejection
of the remediation. No commit, push or deployment change was made. The existing
`m4-events-r5.jsonl` driver artifact was preserved.
