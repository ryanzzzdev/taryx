# M4 independent review — authorised round 4

Candidate: `853842c9ba24c92aa7d487ca3546910eef7107e1` (implementation remediation
`5aad55fc22f6ecd8cdabbb791ec7a0085475bc9a`; subsequent commit records interruption).
Verdict: **CHANGES_REQUESTED**. The driver explicitly authorised this extra round;
`m4-events-r4.jsonl` is an incomplete attempt, not an earlier verdict.

## M4-F8 — high — Consumer correlation check races with a newer transfer

Location: `src/taryx/core/accounts/services.py:50-55`, called from
`src/taryx/core/market/services.py:353-378` without a supply-point row lock.
The new pending correlation check uses an already-loaded model instance.
Worker B can read the old pending point, then worker A can deliver the old
outcome and a new transfer can be admitted. B validates its stale instance
and unconditionally saves `market_state=registered`. The database now contains
the **new** pending correlation with the **old** registered outcome. This
falsely registers the new transfer before it completes.

The round-3 probe interleaves before the supply-point read and passes. The new
`test_consumer_rechecks_correlation_after_concurrent_delivery` interleaves at
the consumer boundary after that read. It uses the real drain, consumer and
admission services; this is a deterministic interleaving, not a live multi-process
stress test. Make validation and mutation atomic against current database state
(e.g. a conditional update on pending state/correlation, or a consistent row-lock
protocol shared with admission). Retain both interleaving probes.

## Resolution and verification scope

- F7: boolean recovery sequence rejected; preserved probe passes.
- F10: the one-attempt budget permits the initial POST; preserved probe passes.
- F11: all four live app containers use image
  `sha256:a692e0cfc467a52674808fdea388900bb8f82000f261cf71bf9f9040de37be28`.
  Named-image Compose configuration and live identity resolve the reported
  cross-client digest discrepancy. See [image inspection](m4-container-images-r4.txt).
- Live provenance caveat: inspecting the **imported** modules with
  `django.setup(); inspect.getsource(module)` and comparing Python ASTs finds
  equivalent account consumer logic but different market submission logic in
  every container: the live module lacks the candidate's immediate at-cap
  HTTP/transport failure transition. [Source comparison](m4-live-source-r4.txt).
  One shared digest proves image identity, not deployment of every candidate
  change. Candidate tests run against the checkout; live isolation observations
  apply to the existing deployment. No deployment was changed in this review.
- Preserved probes: **27 passed**, including live role denial, non-admin broker,
  distinct market credentials, cross-client shadow denial and image identity.
  [Output](m4-probes-r4.txt).

- Expanded probes: **27 passed, 1 failed** on the intended stale-consumer
  assertion (`registered` instead of `pending`). [Output](m4-probes-r4-expanded.txt);
  [runnable probe](m4-probes/test_m4_round4.py).
- `UV_CACHE_DIR=/tmp/taryx-uv-cache make check`: **passed**, 221 backend and
  6 frontend tests, lint/format, mypy, import contracts (including the deliberate
  negative check), frontend types and production build. [Output](m4-check-r4.txt).
- New probe lint/format and `git diff --check`: passed.

## Reproduction and limitations

Run serially (both suites create/drop the test database):

```sh
UV_CACHE_DIR=/tmp/taryx-uv-cache uv run pytest -q docs/project/evidence/m4-probes
UV_CACHE_DIR=/tmp/taryx-uv-cache make check
```

No fresh-volume boot, live kill/restart, billing-under-market-outage campaign,
browser journey, hosted CI or real-market conformance was performed. Existing
bootstrap probes are model tests. M3 approval is unchanged. M4 and TAR-015 remain
In progress for F8. No commit or push; driver JSONL files were preserved.
