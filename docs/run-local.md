# Run Taryx locally

Everything needed to build, start and use the full stack: two isolated
retailer clients (Aurora Energy, Southgrid Retail) sharing one image,
each with its own database, broker vhost, portal, legacy billing
simulator and market simulator.

## Prerequisites

- Docker with Compose (required — the whole stack runs in containers)
- `uv` and Node 22 on the host (only for `make check` / host-side
  commands; not needed just to run the stack)

```text
make install    # optional: uv sync + npm ci for host-side checks
```

## Start

```text
make up         # docker compose up --build (foreground; Ctrl-C to stop)
# or detached:  docker compose up --build -d
```

First build takes a few minutes. `api`/`api-sg` run `migrate` on every
start, so an existing volume is upgraded automatically. The one-shot
`db-init` and `broker-init` jobs provision the second client's role,
database, user and vhost idempotently on each `up`.

## Seed demo data

Run once per client (idempotent — safe to re-run):

```text
docker compose exec api    python manage.py seed_client
docker compose exec api-sg python manage.py seed_client
```

Each seed creates three accounts (ACC-001 bakery, ACC-002 grocer,
ACC-003 studio — ACC-003 carries a mid-period tariff change onto the
GST-exempt heritage agreement), the three demo users below, and a
migration cohort in `legacy_only` routing mode.

Account references and NMIs deliberately overlap between clients —
that's part of the isolation demo.

## Endpoints

| Service | Aurora Energy | Southgrid Retail |
| --- | --- | --- |
| Portal (React) | <http://localhost:5174> | <http://localhost:5175> |
| API (`/healthz`, `/graphql`, `/metrics`) | <http://localhost:8001> | <http://localhost:8002> |
| Legacy billing sim | <http://localhost:18090> | <http://localhost:18091> |
| Market sim | <http://localhost:18092> | <http://localhost:18093> |

Shared infrastructure:

| Service | Endpoint |
| --- | --- |
| PostgreSQL | `localhost:55432` (app connects as `taryx_app` / `taryx_sg`) |
| RabbitMQ AMQP | `localhost:5673` |
| RabbitMQ management | <http://localhost:15673> (`taryx_admin` / `taryx_admin`) |

`/metrics` is an unauthenticated Prometheus-text endpoint with durable
business counters (operations, market workflows, outbox depth).

The `taryx_admin` broker login is the provisioning administrator,
created by `broker-init` on every `up`. The `taryx`/`taryx_sg` users
are non-administrator application accounts scoped to their own vhost —
they cannot log in to the management UI.

Host ports are offset from defaults so sibling project stacks can
coexist; container-internal ports are standard.

## Demo logins

Seeded dev identities (decision 004; never real customers). All three
share the password `multipass`:

| User | Permissions |
| --- | --- |
| `viewer` | read-only queries |
| `operator` | ingest, rate, bill, record discrepancy decisions |
| `approver` | operator actions + approve decisions + cohort transitions |

## Portal journey (what to click)

1. Log in as `operator` on <http://localhost:5174>.
2. **Ingest** a NEM12 file (fixtures live in `tests/fixtures/nem12/`,
   e.g. `day1_base.nem12` covering 2026-03-02 for NMI 4102000001).
3. **Rate** the account for the ingested period, then **Bill** it —
   the portal polls the durable operation until it completes and shows
   the itemised invoice, GST and balanced journal postings.
4. Ingest a revision file (`day1_rev1.nem12`), re-rate, re-bill — an
   adjustment is appended against recognised liability; the original
   invoice is unchanged.
5. **Migration panel**: run a shadow comparison (legacy vs new
   engine), inspect itemised diffs — ACC-001 shows the seeded
   FIT-TRUNC-2003 defect, ACC-003 the heritage GST exemption. Record
   decisions (`operator`), then drive `shadow` → `new_only` cutover as
   `approver`. Every transition is audited in `cohortEvents`.

Log in to <http://localhost:5175> afterwards to see the same accounts
under Southgrid's different catalogue/policy output — same image,
isolated state.

The market-transfer workflow has no portal panel yet — trigger it via
GraphQL or the shell (next section).

## CLI path (same workflow, no UI)

```text
# inside the api container (use api-sg for the second client)
docker compose exec api python manage.py ingest_nem12 /path/to/file.nem12
docker compose exec api python manage.py rate_account ACC-001 2026-03-02 2026-03-03
docker compose exec api python manage.py bill_account ACC-001 2026-03-02 2026-03-03 --op demo-1
docker compose exec api python manage.py drain_outbox        # relay pending events after broker outage
```

`--op` is the idempotency key: retrying `bill_account` with the same
key returns the existing operation instead of double-issuing.

Fixture files aren't in the container image; copy one in first, e.g.
`docker compose cp tests/fixtures/nem12/day1_base.nem12 api:/tmp/` —
or just use the portal ingest.

**Market transfer** (no portal UI — GraphQL `requestTransfer` requires
the `operator` role; the worker sweeps/drains every 10 s):

```text
docker compose exec api python manage.py shell <<'EOF'
from datetime import date
from taryx.core.accounts.models import SupplyPoint
from taryx.core.market.services import request_transfer
from taryx.composition.tasks import market_submit
sp = SupplyPoint.objects.get(nmi="4102000001")
w = request_transfer(sp, date(2026, 3, 2))
market_submit.delay(str(w.correlation_id))
print("submitted", w.correlation_id)
EOF
```

Then watch state: `docker compose exec api python manage.py shell -c
"from taryx.core.market.models import TransferWorkflow; print([(str(w.correlation_id)[:8], w.state) for w in TransferWorkflow.objects.all()])"`
and `curl localhost:18092/transfers` on the sim side.

## Simulator control (fault injection)

Both sims are independent satellite services with admin endpoints.

**Legacy sim** (`:18090` / `:18091`):

```text
GET  /healthz, /v1/version, /_admin/log
POST /_admin/fault        {"mode": "timeout" | "malformed" | "unavailable" | "wrong_protocol" | "ok"}
```

Faults are in-memory; a restart clears them. Every injected fault maps
to an INCONCLUSIVE comparison that blocks the cutover gate.

**Market sim** (`:18092` / `:18093`):

```text
GET  /healthz, /transfers, /transfers/{correlation_id}
POST /_admin/scenario     {"name": "happy" | "business-reject" | "duplicate-callback" |
                          "out-of-order-callback" | "late-completion" | "lost-response" |
                          "malformed-callback", "delay": <seconds>}
POST /_admin/fault        {"mode": "ok" | "unavailable" | "timeout" | "malformed-ack"}
POST /_admin/send_orphan  emits a callback for an unknown correlation id
```

Example — exercise the reconciliation path:

```text
curl -X POST localhost:18092/_admin/scenario -d '{"name": "lost-response"}'
# submit a transfer via the shell snippet above, then watch the adapter reconcile
curl -X POST localhost:18092/_admin/scenario -d '{"name": "happy"}'
```

## Automated journey and verification scripts

`scripts/` contains the M5 evidence drivers — useful when you want the
whole journey or a fault scenario without clicking:

| Script | What it does |
| --- | --- |
| `demo-journey.sh` | Narrated end-to-end run: clean reset, metering, billing, correction, migration cutover, client isolation, market transfer, diagnostics. **It runs `docker compose down -v` itself — it wipes existing volumes.** Run with `DEMO_PAUSE=<seconds>` to slow it down. |
| `fault-campaign.py` | Real-process fault scenarios (SIGKILL around commit, broker outage, duplicate delivery) against the running stack; arms worker fault env hooks. Writes evidence to `docs/project/evidence/m5/`. |
| `measure-budgets.py` | Seeds the R1 measurement estate (100 accounts, April 2026, ~180k intervals). |
| `portfolio-run.py` | Runs the measured portfolio workload against the seeded R1 estate; writes budget evidence to `docs/project/evidence/m5/`. |

## Kubernetes (kind) delivery

The stack also deploys to a local `kind` cluster — StatefulSet
PostgreSQL/RabbitMQ, one shared app image, migration-gated pods,
NetworkPolicy and per-client isolation. See
[deploy/k8s/README.md](../deploy/k8s/README.md) for
`install.sh`/`reset.sh`; `docker compose build api` produces the
`taryx-app:latest` image the manifests expect.

## Stop / reset

```text
make down       # docker compose down — containers stop, volumes persist
make reset      # down -v — drops ALL named volumes: client data and sim state
```

`make reset` wipes everything (PostgreSQL, broker and the sim sqlite
volumes `taryx-legacy*`/`taryx-market*`); re-run the seed commands after
the next `make up`. To reset only the sims while keeping client data,
drop their volumes instead:
`docker volume rm taryx-legacy taryx-legacy-sg taryx-market taryx-market-sg`.

## Checks and troubleshooting

```text
make check      # ruff lint+format, mypy, import contracts, pytest, web test/typecheck/build
```

- **`make up` port conflicts**: all host ports are already offset
  (55432, 5673, 8001/8002, 5174/5175, 18090–18093, 15673). If one still
  clashes, edit the `ports:` mapping in `compose.yaml`.
- **API won't start**: `docker compose logs api db` — Postgres 18
  keeps data under a versioned volume layout; `make reset` fixes a
  volume left by a different major version.
- **Broker errors at start**: the API/worker wait on healthchecks;
  RabbitMQ takes ~15 s. `worker` remote control (inspect/revoke) is
  disabled by design — kombu pidbox queues are rejected by RabbitMQ 4.
- **Portal 403 on first action**: the app bootstraps CSRF with a safe
  GET and retries once automatically; if it persists, hard-reload.
- **`permission_denied` while a tab still shows your role**: cookies are
  host-scoped, not port-scoped — :5174 and :5175 share the `sessionid` /
  `csrftoken` jar. Signing into one client overwrites the other's
  session; the stale tab keeps showing the old role but its calls are
  anonymous. Hard-reload and sign in again. To keep both clients open,
  use different hostnames (`localhost:5174` vs `127.0.0.1:5175`).
- **Stale sims**: legacy/market sqlite files persist in their volumes —
  remove them (above) when changing seeded scenarios.
