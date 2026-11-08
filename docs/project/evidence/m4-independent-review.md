# M4 independent review — round 1

Candidate: `2dbc5b0512d6e6b28b8c15f0730279e55d92a36f`.
Verdict: **CHANGES_REQUESTED**. Scope: TAR-013–015 only; M3 approval is unchanged.

Reviewed decision 005, feature contracts, client composition/policy injection,
Compose and provisioning, adapter/inbox/outbox, HTTP ingress and simulator,
and existing tests. TAR-014's synthetic contract is adequate and remains Done.
TAR-013 and TAR-015 are reopened; M4 remains In progress.

## Findings

### M4-F1 — high — Application database credential can become superuser

`db/init/02-clients.sql:42` grants bootstrap role `taryx` to `taryx_app`
with SET permission. Although SUPERUSER is not inherited automatically,
`SET ROLE taryx` succeeds. A read-only transaction authenticated as `taryx_app`
returned `current_user=taryx, rolsuper=true`. That role can grant cross-database
CONNECT or alter other client roles/data. The direct CONNECT rejection is
therefore not an isolation boundary. Use an application owner without any
superuser membership; confine provisioning authority to provisioning.
Probe: `test_application_role_cannot_become_superuser`.

### M4-F2 — high — Application broker credential retains administrator access

`compose.yaml:11,59-60` supplies Aurora the RabbitMQ bootstrap credential.
Live `rabbitmqctl list_users` reports `taryx [administrator]`. Revoking its
Southgrid vhost permission in `broker/init/provision.py` does not remove its
management authority to re-grant that permission. Use a separate non-admin
application user and keep administrator credentials out of application runtime.
Probe: `test_application_broker_user_is_not_administrator`. No permissions were
changed during review.

### M4-F3 — high — Market credentials are shared across clients

`compose.yaml` market and market-sg both declare `taryx-market-token`; both API
stacks omit overrides for the identical `MARKET_TOKEN` and
`MARKET_CALLBACK_TOKEN` defaults in `src/taryx/config/settings.py`.
An Aurora credential can authenticate to Southgrid's coordinator and callback
endpoint. A known Southgrid correlation can therefore be completed/rejected
using the other client's credential. Use distinct per-deployment credentials
on both directions and test cross-client rejection with no workflow mutation.
Probe: `test_market_credentials_differ_between_clients` (effective Compose config).

### M4-F4 — high — HTTP failures strand drafts after the retry budget

`src/taryx/core/market/services.py:120-125,224-227`: non-409 HTTP errors increment
attempts but never fail at the limit. Sweep subsequently excludes the draft
forever. The simulator's own unavailable mode returns 503 and triggers this
path. Supply points remain pending without recovery. Apply bounded exhaustion
to HTTP errors and make every exhausted draft reach a visible terminal state.
Probe: `test_http_failures_exhaust_to_terminal`.

### M4-F5 — medium — Uncertain submission recovery never polls before resubmit

`src/taryx/core/market/services.py:114-119,224-230`: after an accepted request
whose ack is lost, durable state stays draft and sweep POSTs again without GET.
Repeated lost acknowledgements can end FAILED despite the coordinator having
completed the transfer. A process crash before transaction commit has the same
uncertainty. Decision 005 explicitly requires in-flight submits to re-check GET
before deciding retry versus reconcile. Preserve uncertainty durably and poll
on recovery. Probe: `test_uncertain_submit_polls_before_retry`.

### M4-F6 — high — Sweep can overwrite terminal outcomes

`src/taryx/core/market/services.py:233-247,270-273`: expiry reads submitted rows
without locking, then saves whole stale objects. A callback committed after
that read is overwritten back to reconciling (including its sequence/status).
The later reconciliation loop also fails rows without rechecking state after
locking, including the separate unknown-status transaction. A terminal callback
can thus become FAILED, suppressing its core outbox delivery. Lock and recheck
the current state for every transition; never fail a now-terminal row.
Probe: `test_terminal_callback_during_expiry_cannot_be_overwritten` deterministically
injects a callback between the expiry read and save. This is an interleaving
probe, not a claim of a process-kill campaign.

### M4-F7 — high — Protocol validation admits invalid outcomes and wrong correlations

`src/taryx/core/market/services.py:134,160-166,257-266` and
`src/taryx/core/market/client.py`: callback seq is coerced with `int` (1.5 becomes
1), occurred_at is merely stringified (null becomes `"None"`), and ack/poll
correlation is never checked. A malformed callback completes a workflow;
an unrelated response can submit or complete it. Valid non-object JSON also
escapes the transport as a dict and causes unhandled attribute errors. Validate
message shapes, exact sequence types/ranges, timestamp and UUID/version, and
response correlation before state changes; park/reconcile invalid messages.
Probes: both `test_invalid_callback_cannot_complete` cases and
`test_ack_must_match_correlation`.

### M4-F8 — high — Published core outcome contract is absent

`src/taryx/core/market/services.py:56-96,199-209,278-306`: the outbox has no
version/signature envelope and drain ignores even its topic and payload. A row
with topic `invalid` and payload `{}` still registers the supply point and is
marked delivered. There is no validating core consumer as required by decision
005. Admission/failure/rejection also directly write core account state outside
that consumer, contrary to the stated ownership boundary. Implement and test
the versioned, validated, deduplicated consumer contract; route adapter effects
through it (or explicitly accept a contract amendment before implementing it).
Probe: `test_outbox_validates_envelope`.

## Verification and coverage

- `uv run pytest -q docs/project/evidence/m4-probes`: **10 failed**, each on the
  intended contract assertion; [output](m4-probes-r1.txt). Runnable probes live
  in [m4-probes](m4-probes/). Live isolation probes require Docker access;
  service probes require local PostgreSQL and pytest-django test DB privileges.
- Read-only role verification: [output](m4-isolation-r1.txt); superuser SET ROLE
  was executed inside BEGIN/ROLLBACK, with no grant or business-data changes.
- `UV_CACHE_DIR=/tmp/taryx-uv-cache make check`: **passed**, 197 backend and
  6 frontend tests, lint/format, mypy, import contracts (including the deliberate
  negative probe), frontend typecheck and production build. [Output](m4-check-r1.txt).
- Probe lint and `git diff --check`: passed; HEAD unchanged.
- Policy composition injects client-selected values, rather than accepting a
  request-selected client. Existing policy/import tests cover distinct pricing
  and package independence. Deployment static tests check strings, not effective
  privileges, and missed F1–F3.
- Existing market tests cover sequential transitions and four simulator callback
  patterns. They do not establish process-restart recovery, sweep/callback races,
  response correlation validation, or independent core envelope validation.
  Fake acks omit correlation, masking F7. No live kill/restart or billing-under-
  market-outage campaign was performed here.
- Initial sandbox could not reach PostgreSQL/Docker; approved elevated checks
  succeeded. An initial full-suite attempt overlapped probe database lifecycle
  and was invalidated; the final project check is rerun serially.
- Same-image digest comparison, fresh-volume deployment, browser verification,
  hosted CI and real market conformance were not performed. No implementation
  changes, commits or pushes are part of this review.
