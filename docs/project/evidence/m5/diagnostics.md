# TAR-016a — Correlated diagnostics

Date: 2026-11-13. Scope: logs, metrics, trace join keys, Sentry capture
path. Fault-campaign and budget evidence are separate entries.

## What exists

- `src/taryx/diagnostics.py` — top-level (unconstrained by the layering
  contracts) contextvars, `bind_context`, `ContextFilter`,
  `JsonFormatter`, `install_celery_signals`. Bound fields are a fixed
  allowlist: `request_id`, `task_id`, `task_name`, `operation_id`,
  `correlation_id` — labels are bounded by construction.
- `LOGGING` dictConfig in `src/taryx/config/settings.py` — every
  `taryx.*` logger and the root (celery/django included) emits one JSON
  object per record; `CELERY_WORKER_HIJACK_ROOT_LOGGER = False` keeps
  the format on workers.
- `RequestIdMiddleware` — honours/mints `X-Request-ID` (≤64 chars),
  binds it for the request, echoes it on the response.
- `/metrics` (`src/taryx/interfaces/metrics.py`) — Prometheus text
  exposition of durable counters: billing operations and transfer
  workflows by enum status, market outbox pending, inbox/exceptions,
  `taryx_build_info{client=…}`. Unauthenticated aggregate counts only.
- Task wrappers in `src/taryx/composition/tasks.py` bind
  `operation_id`/`correlation_id`; billing and market services log at
  boundaries (`billing operation finished`, `outbox delivery failed`,
  `transfer outcome applied`, `transfer workflow failed`, `market
  outbox delivery failed/drained`).
- Sentry: `sentry-sdk==2.74.0`, `SENTRY_DSN`-gated `sentry_sdk.init`
  with Django+Celery integrations, `send_default_pii=False`.

## Verified

- `tests/test_diagnostics.py` — 9 tests: bounded context keys,
  redaction (`api_token` → `<redacted>`), truncation, context
  top-level/not-duplicated, celery signal bind/clear, `X-Request-ID`
  echo, `/metrics` bounded output, Sentry envelope capture against an
  in-process transport, DSN gate off by default.
- Live on compose (2026-11-13): `/metrics` returns
  `taryx_billing_operations{status="complete"} 11`,
  `taryx_market_workflows{state="completed"} 1`, pending/exception
  counters, `taryx_build_info{client="aurora_energy"} 1`.
- Worker logs emit JSON with `task_id`/`task_name` stamped by the
  signal binding and the task argument's `operation_id` bound by the
  wrapper; the failing `taryx.billing.process_operation` dispatch shows
  the exception serialized under `exc`.

## Trace model and limits

The trace join keys are the correlation ids themselves: `request_id`
links the API hop, `task_id`/`task_name` link queue↔worker,
`operation_id` links a billing operation end-to-end, `correlation_id`
links the market workflow across adapter and counterparty. This is
honest log correlation, not distributed tracing — no OpenTelemetry/
span model is claimed. Redaction covers values whose keys match
token/password/secret/authorization/api-key patterns; business
payloads are not emitted to logs (raw market payloads stay in the
`MarketException`/`MarketInbox` rows). Sentry export to a real DSN is
unverified — the capture path is proven to the transport boundary
only; hosted delivery, alerting and source-map/PII policy remain
out of scope for the local demo.
