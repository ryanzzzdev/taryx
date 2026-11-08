"""Idempotent southgrid vhost/user provisioning via the management API.

Runs as the one-shot broker-init service; every PUT is upsert-shaped so
re-running is safe. The aurora user `taryx` is intentionally granted no
permissions on taryx-sg — vhost isolation comes from absent grants.
"""

import base64
import json
import os
import urllib.request

BASE = os.environ.get("BROKER_API", "http://broker:15672")
USER = os.environ.get("BROKER_USER", "taryx")
PASSWORD = os.environ.get("BROKER_PASS", "taryx")
VHOST = "taryx-sg"
CLIENT_USER = "taryx_sg"
CLIENT_PASS = "taryx_sg"


def call(method: str, path: str, body: dict | None = None) -> None:
    request = urllib.request.Request(
        f"{BASE}/api/{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Basic "
            + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode(),
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            if response.status not in (201, 204):
                raise SystemExit(f"{method} {path}: HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        # DELETE of an already-absent grant is a successful no-op.
        if not (method == "DELETE" and exc.code == 404):
            raise SystemExit(f"{method} {path}: HTTP {exc.code}")


call("PUT", f"vhosts/{VHOST}")
call("PUT", f"users/{CLIENT_USER}", {"password": CLIENT_PASS, "tags": ""})
call(
    "PUT",
    f"permissions/{VHOST}/{CLIENT_USER}",
    {"configure": ".*", "write": ".*", "read": ".*"},
)
# Creating the vhost through the API grants the calling user full
# permissions on it automatically — revoke them so the aurora
# credential cannot reach the southgrid vhost.
call("DELETE", f"permissions/{VHOST}/{USER}")
print(f"provisioned vhost {VHOST} for {CLIENT_USER}; revoked {USER} access")
