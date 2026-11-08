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

## Remediation — round 1 (2026-11-08)

All eight findings remediated; runnable probes pass (7/7 service, 3/3 live
isolation with the F1 probe accepting the stricter denial outcome).

- **M4-F1** — `taryx_app` is no longer a member of `taryx` at all:
  `REVOKE taryx FROM taryx_app` plus owner-equivalent grants on the existing
  aurora objects (`WITH GRANT OPTION` so migration-time shadow grants still
  work). `SET ROLE` is denied outright — stronger than the probe's
  "succeeds but non-superuser" check; `test_application_role_cannot_become_superuser`
  was amended to accept `CalledProcessError` (permission denied) as passing.
  `taryx` must remain superuser: `taryx_southgrid` is owned by `taryx_sg`, so
  only a superuser can manage its CONNECT grants — the superuser stays
  confined to `db-init` provisioning. `taryx_sg` gains `CREATEROLE` for the
  migration-time shadow-role creation when it migrates first on a fresh cluster.
- **M4-F2** — `taryx` is demoted to a plain vhost-scoped user; a separate
  `taryx_admin` administrator is confined to `broker-init` provisioning
  (fresh volumes create it as `RABBITMQ_DEFAULT_USER`; existing volumes
  bootstrap it through the legacy `taryx` admin, which is then demoted).
- **M4-F3** — per-client market credentials: southgrid gets
  `MARKET_TOKEN`/`MARKET_CALLBACK_TOKEN` `taryx-market-sg-token` on both the
  adapter env and its simulator; aurora tokens are declared explicitly.
- **M4-F4** — non-409 `MarketHttpError` submits count toward the attempt
  budget; exhaustion transitions to `failed` instead of parking a draft the
  sweep can never pick up again.
- **M4-F5** — `submit_workflow` polls `GET /transfers/{correlation_id}`
  before resending when `attempts > 0` (decision-005 in-flight recovery):
  `submitted` re-arms the deadline, a terminal outcome applies through the
  normal callback path, anything else falls through to resubmit.
- **M4-F6** — the expiry→`reconciling` transition is a state-guarded
  `UPDATE ... WHERE state='submitted'` (stale reads can't overwrite a
  committed callback); the reconcile loop re-checks state under its lock
  before the `unknown`→`failed` write.
- **M4-F7** — callback fields are strictly validated (`seq` must be a
  non-negative `int`, `occurred_at` must parse as ISO); submit acks and
  reconcile responses must echo the workflow `correlation_id` or route to
  reconciliation/ignored detail instead of transitioning.
- **M4-F8** — the drain validates the outbox envelope (topic
  `market.transfer_completed`, `version: "1"`, matching `correlation_id`,
  `nmi`, `effective_date`, `occurred_at`) before touching core state;
  invalid events record `attempts`/`last_error` and deliver nothing.

Probe handling: the seven service probes are folded into
`tests/test_market.py` (`TestReviewProbes`); the three live isolation
probes remain in `m4-probes/` (they require a running Docker deployment,
like the earlier live verification artifacts). Verification: probes 10/10;
`make check` green — 205 backend, 6 frontend, lint/format, mypy, import
contracts, TypeScript/build. Live: both workers reconnected on non-admin
credentials; `taryx_app` retains full read/write on aurora objects.

## Round 2 — independent verification (2026-11-08)

Candidate and verified HEAD: `d18312195a4facb3480720854e9f0a863974603b`.
Verdict: **CHANGES_REQUESTED**. M4-F1/F2/F3/F4/F6 are resolved for their reported
cases; M4-F5/F7/F8 remain open, and M4-F9 is new. TAR-013/TAR-015 are reopened;
TAR-014 remains Done, M4 In progress, and M3 approval unchanged. The remediation
section above records implementer claims; this section supersedes its assertion
that all eight findings are resolved.

### Verification of resolved findings and probe integrity

- **M4-F1:** the membership removal fixes the reported escalation. The amended
  probe's intent (accept an actual SET ROLE denial) is valid, but catching every
  `CalledProcessError` also accepted missing Docker, failed authentication or an
  unavailable database. Tightened the preserved probe to require a successful
  `SELECT current_user` as `taryx_app` and the exact permission-denied-to-set-role
  diagnostic, with `ON_ERROR_STOP=1`. It passes against the live deployment.
  This proves the actual denial, not merely a failing subprocess.
- **M4-F2:** the live application broker user is no longer administrator. Reviewed
  the fresh-admin and legacy-bootstrap branches in `broker/init/provision.py`;
  isolated management-API model probes cover both branches and a second run,
  including switching to the new admin after legacy demotion and handling DELETE
  404. Both pass. These model tests do not claim a fresh RabbitMQ-volume boot.
- **M4-F3:** Compose declares distinct adapter/callback and simulator credentials
  for Southgrid; the preserved effective-Compose test passes.
- **M4-F4:** HTTP failure exhaustion now reaches FAILED; preserved probe passes.
- **M4-F6:** guarded expiry UPDATE and locked reconciliation state checks address
  the reported stale transition windows; preserved interleaving probe passes.

### M4-F5 — high — Crash recovery still loses durable submission knowledge

Locations: `src/taryx/core/market/services.py:109-118,124-138,171-182,266-270`.
Polling before resend works after an ordinary caught transport error, but not
across the required crash boundaries:

1. The attempt increment and network POST remain inside one database transaction.
   A crash after remote acceptance rolls the increment back to zero. Recovery
   sees a fresh draft and POSTs again without polling. The new probe injects a
   process-death exception after simulated remote acceptance; GET count is zero
   and POST count is two.
2. Terminal poll recovery saves the incremented attempt count while leaving state
   DRAFT, commits, then invokes `apply_callback` separately. If that application
   is interrupted on attempt five, sweep excludes the draft forever via
   `attempts__lt=max_attempts`. The new probe ends DRAFT instead of COMPLETED.

Persist submit uncertainty before the external side effect and make recovered
outcome application atomic or durably resumable independently of submit budget.
Probes: `test_crash_after_remote_acceptance_requires_poll` and
`test_recovered_terminal_at_budget_survives_crash`. These are deterministic
transaction-boundary simulations, not a live process-kill campaign.

### M4-F7 — high — Missing correlation and non-object JSON remain unvalidated

Locations: `src/taryx/core/market/services.py:299-306` and
`src/taryx/core/market/client.py:70-73`.
Reconcile rejects an explicitly wrong correlation but accepts an absent/null one:
`if correlation is not None ...` bypasses validation. A response containing only
`status: completed, last_seq: 1` completes the workflow and creates an outbox event.
The transport still returns JSON arrays/null/strings as if they were dictionaries;
subsequent `.get` calls can abort a sweep, preventing later rows from progressing.
Require a matching correlation and validated object shape on every response.
Probes: `test_reconcile_missing_correlation_cannot_complete` and three
`test_transport_rejects_nonobject_json` cases fail. R1 callback scalar validation
and wrong-ack-correlation probes now pass, but do not close this broader finding.

### M4-F8 — high — Core envelope validation remains incomplete

Location: `src/taryx/core/market/services.py:354-368` (also admission and rejection
at lines 76-96 and 258).
Topic/version/correlation/NMI checks are improvements, but effective_date and
occurred_at are only tested for truthiness. Replacing either with invalid text
still registers the supply point and marks the event delivered. Effective date
is not compared to the workflow, despite the remediation claim. There are still
no signature fields/validation or distinct validating core consumer, and adapter
admission/failure/rejection still directly mutate account state. Decision 005's
ownership/signature requirements were not amended. Implement the complete
accepted boundary and validation, or obtain an explicit contract change before
claiming completion. Two `test_outbox_rejects_invalid_contract_fields` cases fail.

### M4-F9 — high — Shared runtime shadow credential bypasses client isolation

Locations: `src/taryx/config/settings.py:65-72`, `db/init/02-clients.sql:23-31`,
and the missing per-client shadow overrides in `compose.yaml`.
Both application deployments use `taryx_shadow` with the same credential. That
role is explicitly allowed into both databases and has SELECT on their account
tables. Read-only probes execute inside each API, load its configured shadow
credential, connect to the other client's database, and check effective SELECT
privilege on `accounts_account`: both return `readable`. Separate default DB
roles therefore do not isolate the credentials actually available to each app.
Use separate shadow roles/passwords and per-database grants; retain negative
checks for every runtime credential. This is an M4 cross-client boundary finding,
not a reopening of M3's within-deployment shadow financial-write restrictions.
Probe: both `test_shadow_credential_cannot_read_other_client` cases fail.

### Checks and limitations

- Original candidate probes before reviewer tightening/additions: **10 passed**,
  [m4-probes-r2.txt](m4-probes-r2.txt).
- Final expanded probes: **12 passed, 10 failed**, all failures on intended
  assertions, [m4-probes-r2-expanded.txt](m4-probes-r2-expanded.txt).
  Run `UV_CACHE_DIR=/tmp/taryx-uv-cache uv run pytest -q docs/project/evidence/m4-probes`.
  Added `test_m4_round2.py` and `test_m4_broker_bootstrap.py`; strengthened and
  expanded `test_m4_isolation.py`. Database tests and project tests ran serially.
- `UV_CACHE_DIR=/tmp/taryx-uv-cache make check`: **passed** (205 backend/6 frontend,
  lint/format, mypy, import contracts including intentional negative check,
  frontend typecheck/build), [m4-check-r2.txt](m4-check-r2.txt).
- Probe lint/format and `git diff --check` pass; HEAD unchanged. Only review
  artifacts and affected records changed; pre-existing `m4-events-r2.jsonl`
  belongs to the driver. No commit or push.
- No fresh-volume boot, image-digest comparison, live process-kill/restart,
  billing-under-market-outage, interactive browser or hosted CI verification.
  Broker bootstrap is model-tested; live probes only inspect current services.
  These limits remain distinct from the demonstrated failures above.
