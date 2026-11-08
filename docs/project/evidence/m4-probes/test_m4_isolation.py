"""Read-only live deployment probes; requires local Docker access."""

import json
import subprocess


def compose(*args):
    return subprocess.check_output(["docker", "compose", *args], text=True)


def test_application_role_cannot_become_superuser():
    output = compose(
        "exec",
        "-T",
        "db",
        "sh",
        "-c",
        "PGPASSWORD=taryx_app psql -h localhost -U taryx_app -d taryx "
        '-Atc "BEGIN; SET ROLE taryx; SELECT rolsuper FROM pg_roles '
        'WHERE rolname=current_user; ROLLBACK;"',
    )
    assert "t" not in output.splitlines()


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
