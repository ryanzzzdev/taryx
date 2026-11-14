#!/usr/bin/env bash
# Install or upgrade the kind target. Idempotent: ConfigMaps are
# regenerated from source files and all applies are declarative.
#
# Upgrade procedure: rebuild the app image, `kind load` it, then run
# `./install.sh --rollout`. Migration Jobs are deleted and recreated on
# every run (a completed Job's pod template is immutable, so re-apply
# alone can never run a new pending migration); --rollout additionally
# restarts the app Deployments so the reloaded `latest` image takes
# effect — unchanged pod templates do not roll on plain apply.
set -euo pipefail
cd "$(dirname "$0")/../.."
KUBECTL=${KUBECTL:-kubectl}
ROLLOUT=0
[ "${1:-}" = "--rollout" ] && ROLLOUT=1

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
# Recreate one-shot Jobs so they actually re-run: db-init/broker-provision
# are idempotent, and migrate-* must execute again whenever a new pending
# migration ships. A completed Job can never be re-applied into running.
$KUBECTL -n taryx delete job db-init broker-provision migrate-aurora migrate-southgrid --ignore-not-found
$KUBECTL apply -f deploy/k8s/manifests/30-jobs.yaml
$KUBECTL -n taryx wait --for=condition=ready pod -l taryx.dev/role=broker --timeout=120s
$KUBECTL -n taryx wait --for=condition=complete job/db-init --timeout=120s
$KUBECTL -n taryx wait --for=condition=complete job/broker-provision --timeout=120s
$KUBECTL -n taryx wait --for=condition=complete job/migrate-aurora --timeout=300s
$KUBECTL -n taryx wait --for=condition=complete job/migrate-southgrid --timeout=300s

if [ "$ROLLOUT" = 1 ]; then
  # `latest` + IfNotPresent: apply alone never restarts unchanged pod
  # templates. Restart explicitly so a reloaded image takes effect;
  # the wait-migrated initContainer holds new pods until each client's
  # migrate Job above has completed — the upgrade cannot outrun schema.
  $KUBECTL -n taryx rollout restart deployment/api deployment/worker deployment/api-sg deployment/worker-sg
fi

# Wait on Deployments, not pods: a pod selector can snapshot a pod that
# is mid-deletion during a rollout and die with NotFound.
$KUBECTL -n taryx rollout status deployment/api --timeout=300s
$KUBECTL -n taryx rollout status deployment/worker --timeout=300s
$KUBECTL -n taryx rollout status deployment/api-sg --timeout=300s
$KUBECTL -n taryx rollout status deployment/worker-sg --timeout=300s
$KUBECTL -n taryx wait --for=condition=ready pod -l taryx.dev/role=sim --timeout=120s
echo "install complete; aurora api on node port 30001, southgrid on 30002"
