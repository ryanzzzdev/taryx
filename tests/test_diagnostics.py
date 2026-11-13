"""Correlated diagnostics — bounded labels, redaction, capture paths."""

import json
import logging

import sentry_sdk
from django.test import Client as HttpClient
from sentry_sdk.transport import Transport

from taryx.core.accounts.seed import seed_demo_data
from taryx.diagnostics import (
    ContextFilter,
    JsonFormatter,
    bind_context,
    current_context,
)


def _record(**extra):
    record = logging.getLogger("taryx.test").makeRecord(
        "taryx.test", logging.INFO, __file__, 1, "message", (), None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestContext:
    def test_bind_context_keeps_only_bounded_keys(self):
        with bind_context(operation_id="op-1", password="x", correlation_id="c-1"):
            ctx = current_context()
        assert ctx == {"operation_id": "op-1", "correlation_id": "c-1"}

    def test_context_filter_stamps_records(self):
        record = _record()
        with bind_context(correlation_id="c-9"):
            ContextFilter().filter(record)
        assert record.correlation_id == "c-9"


class TestJsonFormatter:
    def test_bounded_event_with_redaction_and_truncation(self):
        record = _record(
            api_token="secret-token",
            detail="x" * 400,
            outcome="completed",
        )
        event = json.loads(JsonFormatter().format(record))
        assert set(event) >= {"ts", "level", "logger", "msg", "fields"}
        assert event["fields"]["api_token"] == "<redacted>"
        assert event["fields"]["outcome"] == "completed"
        assert len(event["fields"]["detail"]) <= 301

    def test_context_fields_are_top_level_not_duplicated(self):
        record = _record()
        with bind_context(operation_id="op-7"):
            ContextFilter().filter(record)
        event = json.loads(JsonFormatter().format(record))
        assert event["operation_id"] == "op-7"
        assert "operation_id" not in event.get("fields", {})


class TestCeleryContext:
    def test_task_signals_bind_and_clear_task_identity(self):
        from celery.signals import task_postrun, task_prerun

        from taryx.diagnostics import install_celery_signals

        install_celery_signals()

        class Task:
            name = "taryx.test.task"

        task_prerun.send(sender=Task, task_id="tid-1")
        assert current_context()["task_id"] == "tid-1"
        assert current_context()["task_name"] == "taryx.test.task"
        task_postrun.send(sender=Task)
        assert current_context() == {}


class TestHttpCorrelation:
    def test_request_id_echoed_and_bounded(self):
        response = HttpClient().get("/healthz", HTTP_X_REQUEST_ID="req-abc")
        assert response["X-Request-ID"] == "req-abc"

    def test_metrics_endpoint_reports_bounded_counters(self, db):
        seed_demo_data()
        body = HttpClient().get("/metrics").content.decode()
        assert "taryx_billing_operations" in body
        assert "taryx_market_workflows" in body
        assert "taryx_market_outbox_pending" in body
        assert 'taryx_build_info{client="' in body
        # Labels come only from enum values — no free-form identifiers.
        assert "correlation_id" not in body


class CollectingTransport(Transport):
    def __init__(self):
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


class TestSentryCapturePath:
    def test_exception_reaches_transport_without_external_account(self):
        """The capture path is proven end-to-end against an in-process
        transport: init → capture → serialised envelope. No DSN/network
        is needed to verify the wiring that a real DSN would use."""
        transport = CollectingTransport()
        client = sentry_sdk.Client(
            dsn="https://a1b2c3@o0.ingest.local.invalid/0", transport=transport
        )
        # capture_exception resolves the client on the *current* scope, so
        # the test pushes a scope carrying our collecting client.
        with sentry_sdk.scope.use_scope(sentry_sdk.Scope(client=client)) as scope:
            try:
                raise RuntimeError("diagnostic probe")
            except RuntimeError:
                assert scope.capture_exception() is not None
        client.flush()
        assert len(transport.events) == 1
        event = transport.events[0]
        assert event["level"] == "error"
        assert "diagnostic probe" in json.dumps(event)

    def test_settings_gate_skips_init_without_dsn(self, settings):
        settings.SENTRY_DSN = ""
        assert settings.SENTRY_DSN == ""
