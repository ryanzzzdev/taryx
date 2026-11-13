# Kubernetes delivery (kind)

Plain manifests under `manifests/` plus two scripts. Target: a local
`kind` cluster; no Helm and no cloud account required.

## Install

```bash
kind create cluster --name taryx
docker compose build api            # taryx-app:latest
docker build -t taryx-market-sim:latest market-sim
docker build -t taryx-legacy-sim:latest legacy-sim
kind load docker-image taryx-app:latest taryx-market-sim:latest taryx-legacy-sim:latest --name taryx
bash deploy/k8s/install.sh
```

`install.sh` is idempotent. It generates ConfigMaps from
`db/init/*.sql` and `broker/init/provision.py` so the cluster always
runs committed sources, then applies manifests in dependency order.
Application pods are applied **before** their migration Jobs on
purpose: each api/worker pod runs a `wait-migrated` initContainer
(`migrate --check` loop), so a pending or failed migration Job holds
the workload in `Init` — unsafe advancement is impossible by
construction, and the gate is observable in `kubectl get pods`.

## Topology

- `db` StatefulSet (postgres:18.6, PVC): `taryx` + `taryx_southgrid`
  databases with per-client roles — same isolation model as compose.
- `broker` StatefulSet (rabbitmq management, PVC): `taryx` and
  `taryx-sg` vhosts; provisioner admin is confined to the Job.
- `api`/`worker` and `api-sg`/`worker-sg` Deployments: one image
  (`taryx-app:latest`) — same-build evidence for both clients.
- `legacy`/`legacy-sg`/`market`/`market-sg` sims: `emptyDir` — their
  state is synthetic and a pod restart is the documented reset.
- `api`/`api-sg` are NodePort services (30001/30002).

## Reset boundary

```bash
bash deploy/k8s/reset.sh
```

Deletes controllers (so nothing recreates pods mid-reset), pods, jobs
and both PVCs, then reinstalls. Persistent state lives only in the
`pgdata-db-0` and `data-broker-0` PVCs; everything else is rebuilt.

## Boundaries exercised (evidence: docs/project/evidence/m5/kubernetes.md)

- NetworkPolicy: unlabeled pods cannot reach `db:5432` or
  `broker:5672/15672`; the API edge (8000) stays open; the management
  API is reachable only from the provisioning Job.
- Credentials: cross-client `psql` is denied in both directions.
- Worker lifecycle: `--grace-period=0` deletion leaves an operation
  pending with zero financial effect; a graceful delete lets celery
  warm-shutdown finish the in-flight task.
- Scaling: `worker` scaled to 2 with duplicate task deliveries —
  exactly one invoice per operation, queue drained to 0.
