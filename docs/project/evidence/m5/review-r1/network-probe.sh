#!/usr/bin/env bash
# Uses an existing kind installation; creates/deletes one unlabeled probe pod.
set -euo pipefail
kubectl -n taryx run m5-review-network --image=taryx-app:latest --image-pull-policy=IfNotPresent --restart=Never --attach --rm --command -- python -c 'import socket; socket.create_connection(("db",5432),3); print("UNEXPECTED: unlabeled pod reached db")'
# A connection timeout (nonzero exit) is the expected isolation result.
