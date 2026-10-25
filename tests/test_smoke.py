import pytest
from django.test import Client

from taryx.interfaces.graphql.schema import schema


def test_ping_query_resolves():
    result = schema.execute("{ ping version }")
    assert not result.errors
    assert result.data == {"ping": "pong", "version": "0.1.0"}


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
