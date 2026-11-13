# TAR-017 — Kubernetes delivery evidence (kind)

Date: 2026-11-13. Cluster: `kind create cluster --name taryx` (kind
v0.27, K8s 1.34, kindnetd). Images: `taryx-app:latest` (one image for
all four app pods), `taryx-market-sim:latest`, `taryx-legacy-sim:latest`
loaded via `kind load docker-image`. Manifests: `deploy/k8s/manifests/`,
driver `deploy/k8s/install.sh` (idempotent; ConfigMaps are generated
from `db/init/*.sql` and `broker/init/provision.py` at apply time).

## Fresh-cluster start

`install.sh` applies both clients end-to-end. Final state (after the
fixes below): db-0, broker-0, api/api-sg, worker/worker-sg, all four
sims Running+Ready; db-init, broker-provision and both migrate Jobs
Completed. `curl http://<node-ip>:30001/healthz` and `:30002/healthz`
return `{"status":"ok"}`; worker logs show JSON events with bound
`task_id`/`task_name` (the TAR-016a diagnostics carry over unchanged).

Build-out fixes recorded honestly:

- postgres:18.6 rejects a PVC mounted at `/var/lib/postgresql/data`
  (expects the parent dir; data subdir is created by initdb). Mounted
  at `/var/lib/postgresql`.
- `args:` alone cannot override a Dockerfile CMD in Kubernetes — it
  became the executable (`exec: "--port": executable file not found`).
  Removed; the image's own CMD is used.
- `rabbitmq-diagnostics ping` exceeded the default 1 s exec-probe
  timeout on a loaded node → `timeoutSeconds: 10`, plus
  `publishNotReadyAddresses` so the provisioning Job could resolve the
  headless service during the slow first boot.
- First `reset.sh` deadlocked: `kubectl delete pvc` waits for
  finalizers, but bound PVCs cannot finalize while controllers keep
  recreating pods. Fixed ordering — controllers → pods → PVCs.

## Migration gate

api/api-sg/worker/worker-sg run a `wait-migrated` initContainer looping
`python manage.py migrate --check`. Observed `Init:0/1` on all four app
pods while `db` was still starting; pods became Ready only after their
client's `migrate-*` Job reached Complete (migrate + `seed_client`).
A failed or pending migration therefore cannot be outrun by the
workload — demonstrated by construction and observed in `kubectl get
pods` during install.

## Network and credential boundaries

- From an unlabeled probe pod: `psql` to `db:5432` never connects
  (NetworkPolicy `db-ingress` allows only api/worker/job pods);
  `</dev/tcp/broker/5672` times out (`broker-ingress`); `api:8000` is
  OPEN (deliberate edge, NodePort clients and sim callbacks).
- Credential layer: from a `taryx.dev/role=job` probe pod (network-
  permitted), `psql postgresql://taryx_app@db/taryx_southgrid` →
  `FATAL: permission denied for database` (CONNECT revoked), and
  `taryx_sg@db/taryx` likewise denied — both directions, while each
  role reads its own database (3 seeded accounts each).

## Worker lifecycle

- Forced kill: `TARYX_BILLING_PRECOMMIT_SLEEP=20` armed on the worker;
  `bill_account` op `k8s-kill-1` dispatched; pod force-deleted
  (`--grace-period=0`) while the task was in-flight → op `pending`,
  0 invoices. `drain_outbox` → `complete`, exactly 1 invoice/1 journal.
- Graceful: `bill_account` op `k8s-grace-1` in-flight inside the same
  sleep hook; `kubectl delete pod` (SIGTERM, 60 s grace) → celery warm
  shutdown finished the task: op `complete`, invoice written, no
  recovery needed.
- Queue-based scaling: `worker` scaled to 2; three ops dispatched with
  a duplicate `process_billing_operation` delivery each. All `complete`,
  total invoices 5 for five billing periods (one per operation),
  `celery` queue depth 0 after drain — bounded.

## Reset boundary

`reset.sh` run end-to-end: controllers/pods/jobs removed, both PVCs
recreated on reinstall. Post-reset DB shows only the deterministic
seed (3 accounts, 0 invoices, 0 operations, 0 ingestion batches) and
the broker shows both vhosts reprovisioned.

## Limits

Single-node kind; no multi-AZ or pod-disruption budget claims. Egress
is unrestricted (ingress-side policies only); DNS relies on cluster
DNS. `runserver` is used for the api container (same as compose) — no
production ingress/TLS is claimed. Secrets are literal dev values in
`01-secrets.yaml`, matching the compose defaults.

## Failed rollout cannot advance (2026-11-13)

Deliberately broke the `wait-migrated` initContainer on the `api`
deployment (`command: exit 1`) and restarted the rollout. Observed:

- new replica stuck `Init:Error` / `Init:CrashLoopBackOff` — the
  migration gate cannot be outrun even by a manual rollout;
- old replica stayed `1/1 Running` and `http://172.22.0.2:30001/healthz`
  kept answering `200` — a failed rollout stalls rather than dropping
  the service (bounded availability: the previous version keeps
  serving; there is no zero-downtime guarantee);
- restoring the init command rolled the deployment out cleanly.

Recovery path recorded: fix the failing migration/init (or
`kubectl rollout undo` to the last good revision — note the restart
annotation creates its own revision, so `--to-revision` or a direct
patch is needed when multiple revisions carry the defect).
