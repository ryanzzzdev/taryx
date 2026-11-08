"""Isolated management-API model: no live broker mutations."""

import base64
import json
import runpy
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "broker/init/provision.py"


@pytest.mark.parametrize("legacy", [False, True])
def test_broker_bootstrap_and_repeat(legacy, monkeypatch):
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
        runpy.run_path(str(SCRIPT))
        runpy.run_path(str(SCRIPT))
    assert users == {"taryx": "", "taryx_admin": "administrator", "taryx_sg": ""}
    assert grants == {"permissions/taryx/taryx", "permissions/taryx-sg/taryx_sg"}
