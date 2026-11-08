"""Idempotent broker provisioning via the management API.

Runs as the one-shot broker-init service. The administrative credential
(`taryx_admin`) is confined to provisioning; application users are
non-administrator accounts scoped to their own vhost. Every PUT is
upsert-shaped so re-running is safe; the first run on an existing
volume may need the legacy bootstrap admin (`taryx`), which is then
demoted to a plain user.
"""

import base64
import json
import os
import urllib.request

BASE = os.environ.get("BROKER_API", "http://broker:15672")
ADMIN = os.environ.get("BROKER_USER", "taryx_admin")
ADMIN_PASS = os.environ.get("BROKER_PASS", "taryx_admin")
# Legacy bootstrap: existing volumes created the `taryx` user as the
# default admin; fresh volumes create `taryx_admin` instead.
BOOTSTRAP = (
    os.environ.get("BROKER_BOOTSTRAP_USER", "taryx"),
    os.environ.get("BROKER_BOOTSTRAP_PASS", "taryx"),
)
VHOST = "taryx-sg"
CLIENT_USER = "taryx_sg"
CLIENT_PASS = "taryx_sg"

_auth = {"header": ""}


def _header(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def call(
    method: str, path: str, body: dict | None = None, as_user: tuple[str, str] | None = None
) -> None:
    request = urllib.request.Request(
        f"{BASE}/api/{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            "Authorization": _header(*as_user) if as_user else _auth["header"],
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            if response.status not in (200, 201, 204):
                raise SystemExit(f"{method} {path}: HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise PermissionError from exc
        # DELETE of an already-absent grant is a successful no-op.
        if not (method == "DELETE" and exc.code == 404):
            raise SystemExit(f"{method} {path}: HTTP {exc.code}") from exc


# Authenticate as the provisioning admin; bootstrap once through the
# legacy admin on volumes that predate taryx_admin.
_auth["header"] = _header(ADMIN, ADMIN_PASS)
try:
    call("GET", "users")
except PermissionError:
    call(
        "PUT",
        f"users/{ADMIN}",
        {"password": ADMIN_PASS, "tags": "administrator"},
        as_user=BOOTSTRAP,
    )
    call("PUT", f"users/{BOOTSTRAP[0]}", {"password": BOOTSTRAP[1], "tags": ""}, as_user=BOOTSTRAP)
    print(f"bootstrapped {ADMIN}; demoted legacy admin {BOOTSTRAP[0]}")
    _auth["header"] = _header(ADMIN, ADMIN_PASS)

# Aurora's application user is a plain (non-administrator) account
# scoped to its own vhost.
call("PUT", "users/taryx", {"password": "taryx", "tags": ""})
call("PUT", "permissions/taryx/taryx", {"configure": ".*", "write": ".*", "read": ".*"})

# Southgrid: own vhost and non-administrator user.
call("PUT", f"vhosts/{VHOST}")
call("PUT", f"users/{CLIENT_USER}", {"password": CLIENT_PASS, "tags": ""})
call(
    "PUT",
    f"permissions/{VHOST}/{CLIENT_USER}",
    {"configure": ".*", "write": ".*", "read": ".*"},
)
# Creating the vhost through the API grants the calling user full
# permissions on it automatically — revoke so no aurora credential
# can reach the southgrid vhost.
call("DELETE", f"permissions/{VHOST}/{ADMIN}")
call("DELETE", f"permissions/{VHOST}/taryx")
print(f"provisioned vhost {VHOST} for {CLIENT_USER}; taryx is non-admin")
