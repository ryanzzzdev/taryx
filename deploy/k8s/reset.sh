#!/usr/bin/env bash
# Explicit reset boundary: deletes application data (PVCs) and jobs,
# then re-runs install. Persistent state lives only in the db/broker
# PVCs; simulator /data is emptyDir and resets with every pod restart.
# Order matters: controllers must go first so they cannot recreate pods
# that re-claim the PVCs being deleted.
set -euo pipefail
cd "$(dirname "$0")/../.."
KUBECTL=${KUBECTL:-kubectl}
$KUBECTL -n taryx delete statefulset,deployment,job --all --ignore-not-found
$KUBECTL -n taryx wait --for=delete pod --all --timeout=180s || true
$KUBECTL -n taryx delete pvc --all --ignore-not-found
$KUBECTL -n taryx wait --for=delete pvc --all --timeout=120s || true
exec bash deploy/k8s/install.sh
