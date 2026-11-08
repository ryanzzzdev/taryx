"""Deployment isolation declarations: two clients, separated planes.

Static checks on the compose topology and the provisioning scripts —
the runtime evidence (refused CONNECT, refused vhost, distinct seeded
accounts) is produced by `docker compose up`; these tests keep the
declarations that produce it honest.
"""

import base64
import json
import re
import runpy
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "compose.yaml").read_text()
DB_INIT = (ROOT / "db" / "init" / "02-clients.sql").read_text()
BROKER_INIT = (ROOT / "broker" / "init" / "provision.py").read_text()


def _env_anchor(name: str) -> str:
    """Return the env block following `x-{name}-env: &{name}-env`."""
    match = re.search(rf"x-{name}-env:[^\n]*\n(.*?)(?=\n\S|\Z)", COMPOSE, re.S)
    assert match, f"no x-{name}-env anchor in compose.yaml"
    return match.group(1)


def test_second_client_has_own_database_and_role():
    assert "taryx_southgrid" in DB_INIT
    assert "taryx_sg" in DB_INIT
    # Both directions of CONNECT are closed — not just the new client.
    assert "REVOKE CONNECT ON DATABASE taryx FROM PUBLIC" in DB_INIT
    assert "REVOKE CONNECT ON DATABASE taryx_southgrid FROM PUBLIC" in DB_INIT


def test_aurora_app_does_not_use_bootstrap_superuser():
    """The superuser credential is confined to provisioning; the aurora
    app role is never a member of it (SET ROLE would restore full
    power) — it holds owner-equivalent grants on aurora objects only."""
    aurora = _env_anchor("taryx")
    assert "POSTGRES_USER: taryx_app" in aurora
    assert "POSTGRES_USER: taryx\n" not in aurora
    assert "GRANT taryx TO taryx_app" not in DB_INIT
    assert "REVOKE taryx FROM taryx_app" in DB_INIT


def test_second_client_has_own_broker_vhost_and_user():
    assert "taryx-sg" in BROKER_INIT
    assert "taryx_sg" in BROKER_INIT
    # The vhost creator auto-gets permissions; the provisioner revokes them.
    assert re.search(r'DELETE", f"permissions/', BROKER_INIT)


def test_application_broker_users_are_not_administrators():
    """An administrator could re-grant itself the other client's vhost;
    app credentials must carry no tags, and the provisioning admin is
    confined to broker-init."""
    assert re.search(r'users/taryx", \{"password": "taryx", "tags": ""\}', BROKER_INIT)
    assert re.search(r'users/\{CLIENT_USER\}.*"tags": ""', BROKER_INIT)
    # The only administrator tag is the provisioning admin itself.
    assert BROKER_INIT.count('"administrator"') == 1
    aurora = _env_anchor("taryx")
    assert "amqp://taryx_admin" not in aurora


def test_southgrid_environment_is_fully_separate():
    env = _env_anchor("southgrid")
    assert "POSTGRES_DB: taryx_southgrid" in env
    assert "POSTGRES_USER: taryx_sg" in env
    assert "taryx_sg:taryx_sg@broker:5672/taryx-sg" in env
    assert "TARYX_CLIENT: southgrid_retail" in env
    assert "LEGACY_BASE_URL: http://legacy-sg:8090" in env
    # The settings default only trusts the aurora portal origin; each
    # client's portal origin must be declared or logins 403 on Origin.
    assert "DJANGO_CSRF_TRUSTED_ORIGINS" in env
    assert "localhost:5175" in env
    # No shared secret with the aurora block.
    assert "taryx@broker" not in env
    # Per-client market credentials: a shared token would let one
    # client's simulator authenticate against the other's adapter.
    assert "MARKET_TOKEN: taryx-market-sg-token" in env
    assert "MARKET_CALLBACK_TOKEN: taryx-market-sg-token" in env
    assert "MARKET_TOKEN: taryx-market-token" in _env_anchor("taryx")


def test_second_stack_services_and_provisioning_order():
    for svc in ("api-sg", "worker-sg", "legacy-sg", "web-sg"):
        assert re.search(rf"^  {svc}:", COMPOSE, re.M), f"{svc} missing"
    api_sg = COMPOSE.split("  api-sg:")[1].split("  worker-sg:")[0]
    assert "db-init" in api_sg
    assert "broker-init" in api_sg
    # Each client keeps its own legacy evidence store.
    assert "taryx-legacy-sg" in COMPOSE


def test_shadow_credentials_are_client_scoped():
    """M4-F9: the shared shadow role must never reach another client's
    database — each deployment resolves its own shadow credential."""
    assert "POSTGRES_SHADOW_USER: taryx_shadow_sg" in _env_anchor("southgrid")
    assert "POSTGRES_SHADOW_USER: taryx_shadow\n" in _env_anchor("taryx")
    assert "REVOKE CONNECT ON DATABASE taryx_southgrid FROM taryx_shadow" in DB_INIT
    assert "GRANT CONNECT ON DATABASE taryx_southgrid TO taryx_shadow_sg" in DB_INIT
    assert "taryx_shadow_sg" in DB_INIT
    # Migration 0005 resolves the per-database shadow role from the GUC.
    m5 = next((ROOT / "src/taryx/core/migration/migrations").glob("0005_*.py"))
    assert "taryx.shadow_role" in m5.read_text()


@pytest.mark.parametrize("legacy", [False, True])
def test_broker_bootstrap_and_repeat(legacy, monkeypatch):
    """The provisioner bootstrap works on a legacy volume (taryx admin)
    and a fresh volume (taryx_admin), and re-running is idempotent."""
    monkeypatch.setenv("BROKER_USER", "taryx_admin")
    monkeypatch.setenv("BROKER_PASS", "taryx_admin")
    monkeypatch.setenv("BROKER_BOOTSTRAP_USER", "taryx")
    monkeypatch.setenv("BROKER_BOOTSTRAP_PASS", "taryx")
    users = {"taryx" if legacy else "taryx_admin": "administrator"}
    grants = set()

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def request(req):
        user, password = (
            base64.b64decode(req.get_header("Authorization").split()[1]).decode().split(":")
        )
        if users.get(user) != "administrator" or user != password:
            raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, None)
        path = req.full_url.split("/api/")[1]
        method = req.get_method()
        if method == "PUT" and path.startswith("users/"):
            users[path.split("/")[1]] = json.loads(req.data)["tags"]
        elif method == "PUT" and path.startswith("permissions/"):
            grants.add(path)
        elif method == "DELETE":
            if path not in grants:
                raise urllib.error.HTTPError(req.full_url, 404, "absent", {}, None)
            grants.remove(path)
        return Response()

    with patch("urllib.request.urlopen", side_effect=request):
        runpy.run_path(str(ROOT / "broker" / "init" / "provision.py"))
        runpy.run_path(str(ROOT / "broker" / "init" / "provision.py"))
    assert users == {"taryx": "", "taryx_admin": "administrator", "taryx_sg": ""}
    assert grants == {"permissions/taryx/taryx", "permissions/taryx-sg/taryx_sg"}
