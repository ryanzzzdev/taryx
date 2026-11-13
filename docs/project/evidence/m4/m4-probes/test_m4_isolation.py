"""Read-only live deployment probes; requires local Docker access."""

import json
import subprocess

import pytest


def compose(*args):
    return subprocess.check_output(["docker", "compose", *args], text=True)


def test_application_role_cannot_become_superuser():
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "db",
            "sh",
            "-c",
            "PGPASSWORD=taryx_app psql -h localhost -U taryx_app -d taryx "
            "-v ON_ERROR_STOP=1 -Atc 'SELECT current_user' "
            "-c 'BEGIN; SET ROLE taryx; SELECT rolsuper FROM pg_roles "
            "WHERE rolname=current_user; ROLLBACK;'",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert "taryx_app" in result.stdout.splitlines(), result.stderr
    if result.returncode:
        assert 'permission denied to set role "taryx"' in result.stderr, result.stderr
    else:
        assert "t" not in result.stdout.splitlines()


def test_application_broker_user_is_not_administrator():
    output = compose("exec", "-T", "broker", "rabbitmqctl", "list_users")
    row = next(line for line in output.splitlines() if line.startswith("taryx\t"))
    assert "administrator" not in row


def test_market_credentials_differ_between_clients():
    config = json.loads(compose("config", "--format", "json"))["services"]
    assert (
        config["market"]["environment"]["MARKET_TOKEN"]
        != config["market-sg"]["environment"]["MARKET_TOKEN"]
    )


@pytest.mark.parametrize(
    "service,other_database", [("api", "taryx_southgrid"), ("api-sg", "taryx")]
)
def test_shadow_credential_cannot_read_other_client(service, other_database):
    # Use the credential configured inside each application, not an admin account.
    script = f"""
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taryx.config.settings")
from django.conf import settings
import psycopg
c = settings.DATABASES["shadow"]
try:
    conn = psycopg.connect(dbname={other_database!r}, user=c["USER"],
    password=c["PASSWORD"], host=c["HOST"], port=c["PORT"])
except psycopg.OperationalError as exc:
    if "permission denied" not in str(exc):
        raise
    print("denied")
else:
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT has_table_privilege(current_user, 'accounts_account', 'SELECT')")
            print("readable" if cursor.fetchone()[0] else "denied")
"""
    assert compose("exec", "-T", service, "python", "-c", script).strip() == "denied"


def test_clients_run_same_application_image():
    output = subprocess.check_output(
        [
            "docker",
            "inspect",
            "taryx-api-1",
            "taryx-api-sg-1",
            "taryx-worker-1",
            "taryx-worker-sg-1",
            "--format",
            "{{.Image}}",
        ],
        text=True,
    )
    assert len(set(output.splitlines())) == 1
