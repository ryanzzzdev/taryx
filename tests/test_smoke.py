import pytest
from django.test import Client

from taryx.composition.policy import policy, selected_client_id
from taryx.interfaces.graphql.schema import schema


def test_ping_query_resolves():
    # Clear the policy-selection cache so this smoke test is not affected
    # by earlier tests that monkeypatch TARYX_CLIENT.
    selected_client_id.cache_clear()
    policy.cache_clear()
    client_name = policy().CLIENT_NAME

    result = schema.execute("{ ping version clientName }")
    assert not result.errors
    assert result.data == {
        "ping": "pong",
        "version": "0.1.0",
        "clientName": client_name,
    }


@pytest.mark.django_db
def test_healthz_reports_database_ok():
    response = Client().get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_graphql_endpoint_serves_query():
    response = Client().post(
        "/graphql",
        data={"query": "{ ping }"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"ping": "pong"}


def test_smoke_task_registered_on_celery_app():
    import taryx.interfaces.tasks  # noqa: F401
    from taryx.config.celery import app

    assert "taryx.smoke.ping" in app.tasks
