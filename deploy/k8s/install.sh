#!/usr/bin/env bash
# Fresh-cluster install for the kind target. Idempotent: ConfigMaps are
# regenerated from source files and all applies are declarative.
set -euo pipefail
cd "$(dirname "$0")/../.."
KUBECTL=${KUBECTL:-kubectl}

kubectl apply -f deploy/k8s/manifests/00-namespace.yaml
kubectl apply -f deploy/k8s/manifests/01-secrets.yaml
kubectl apply -f deploy/k8s/manifests/02-env.yaml

# Init/provision sources are generated from the repo files, so the
# cluster always runs what is committed — no embedded copies to drift.
$KUBECTL -n taryx create configmap taryx-db-init \
  --from-file=db/init/01-shadow-role.sql \
  --from-file=db/init/02-clients.sql \
  --dry-run=client -o yaml | $KUBECTL apply -f -
$KUBECTL -n taryx create configmap taryx-broker-init \
  --from-file=provision.py=broker/init/provision.py \
  --dry-run=client -o yaml | $KUBECTL apply -f -

$KUBECTL apply -f deploy/k8s/manifests/10-postgres.yaml
$KUBECTL apply -f deploy/k8s/manifests/11-rabbitmq.yaml
$KUBECTL apply -f deploy/k8s/manifests/20-sims.yaml
$KUBECTL apply -f deploy/k8s/manifests/60-networkpolicy.yaml

# Workloads are applied BEFORE their migration Jobs on purpose: the
# wait-migrated initContainer holds api/worker in Init until each
# client's migrate Job completes — the rollout gate is observable.
$KUBECTL apply -f deploy/k8s/manifests/40-api.yaml
$KUBECTL apply -f deploy/k8s/manifests/50-worker.yaml

$KUBECTL -n taryx wait --for=condition=ready pod -l taryx.dev/role=db --timeout=120s
$KUBECTL apply -f deploy/k8s/manifests/30-jobs.yaml
$KUBECTL -n taryx wait --for=condition=ready pod -l taryx.dev/role=broker --timeout=120s
$KUBECTL -n taryx wait --for=condition=complete job/db-init --timeout=120s
$KUBECTL -n taryx wait --for=condition=complete job/broker-provision --timeout=120s
$KUBECTL -n taryx wait --for=condition=complete job/migrate-aurora --timeout=300s
$KUBECTL -n taryx wait --for=condition=complete job/migrate-southgrid --timeout=300s

$KUBECTL -n taryx wait --for=condition=ready pod -l taryx.dev/role=api --timeout=300s
$KUBECTL -n taryx wait --for=condition=ready pod -l taryx.dev/role=worker --timeout=300s
$KUBECTL -n taryx wait --for=condition=ready pod -l taryx.dev/role=sim --timeout=120s
echo "install complete; aurora api on node port 30001, southgrid on 30002"
