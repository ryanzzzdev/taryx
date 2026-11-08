"""Market adapter tests — the decision-005 transition table end to end.

Service-level tests inject a fake counterparty client; the final class
spawns the real `market_sim.py` subprocess over HTTP to prove the wire
shapes, idempotent resubmission and callback delivery agree.
"""

import io
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.test import Client as HttpClient
from django.test import override_settings
from django.utils import timezone

from taryx.core.accounts.seed import seed_demo_data
from taryx.core.market.client import MarketClient, MarketTransport
from taryx.core.market.models import (
    MarketException,
    MarketInbox,
    MarketOutbox,
)
from taryx.core.market.services import (
    apply_callback,
    drain_market_outbox,
    request_transfer,
    submit_workflow,
    sweep,
)

ROOT = Path(__file__).resolve().parent.parent
SIM = ROOT / "market-sim" / "market_sim.py"


@pytest.fixture
def t0():
    return timezone.now()


class FakeClient:
    """Scripted counterparty: queued submit acks and poll responses."""

    def __init__(self, posts=None, gets=None):
        self.posts = list(posts or [])
        self.gets = list(gets or [])
        self.post_calls = []
        self.get_calls = []

    def post(self, path, body):
        self.post_calls.append((path, body))
        item = self.posts.pop(0)
        if isinstance(item, Exception):
            raise item
        item.setdefault("correlation_id", body["correlation_id"])
        return item

    def get(self, path):
        self.get_calls.append(path)
        if not self.gets:
            raise MarketTransport("no scripted response")
        item = self.gets.pop(0)
        if isinstance(item, Exception):
            raise item
        item.setdefault("correlation_id", path.rsplit("/", 1)[-1])
        return item


def _callback(workflow, seq=1, outcome="completed"):
    return {
        "correlation_id": str(workflow.correlation_id),
        "seq": seq,
        "outcome": outcome,
        "occurred_at": "2026-03-02T00:00:00Z",
    }


@pytest.fixture
def supply_point(db):
    accounts = seed_demo_data()
    return accounts[0].supply_points.get()


@pytest.fixture
def submitted(supply_point, t0):
    workflow = request_transfer(supply_point, t0.date())
    submit_workflow(
        workflow.correlation_id,
        client=FakeClient(posts=[{"status": "submitted", "seq": 0}]),
        now=t0,
    )
    workflow.refresh_from_db()
    return workflow


class TestTransitions:
    def test_happy_path_completes_and_registers(self, db, supply_point, submitted):
        assert submitted.state == "submitted"
        assert supply_point.market_state == "pending"
        result = apply_callback(_callback(submitted))
        assert result == {"status": "completed"}
        submitted.refresh_from_db()
        assert submitted.state == "completed"
        assert submitted.last_applied_seq == 1
        # Terminal outcome publishes exactly one outbox event; the drain
        # is what touches core state.
        assert MarketOutbox.objects.filter(workflow=submitted).count() == 1
        supply_point.refresh_from_db()
        assert supply_point.market_state == "pending"
        assert drain_market_outbox() == 1
        supply_point.refresh_from_db()
        assert supply_point.market_state == "registered"

    def test_duplicate_callback_one_transition(self, db, supply_point, submitted):
        apply_callback(_callback(submitted))
        assert apply_callback(_callback(submitted)) == {"status": "duplicate"}
        assert MarketOutbox.objects.count() == 1
        assert MarketInbox.objects.count() == 1

    def test_lower_seq_after_terminal_is_late(self, db, submitted):
        apply_callback(_callback(submitted, seq=2))
        # seq 1 arrives after seq 2 already completed the workflow —
        # recorded, but the terminal state cannot be overwritten.
        assert apply_callback(_callback(submitted, seq=1, outcome="rejected")) == {"status": "late"}
        submitted.refresh_from_db()
        assert submitted.state == "completed"
        assert MarketInbox.objects.get(seq=1).note == "late"

    def test_business_reject_is_terminal_without_outbox(self, db, supply_point, submitted):
        assert apply_callback(_callback(submitted, outcome="rejected")) == {"status": "rejected"}
        submitted.refresh_from_db()
        assert submitted.state == "rejected"
        assert MarketOutbox.objects.count() == 0
        supply_point.refresh_from_db()
        assert supply_point.market_state == "none"

    def test_unknown_correlation_parks_exception(self, db, submitted, t0):
        result = apply_callback(
            {
                "correlation_id": str(uuid4()),
                "seq": 1,
                "outcome": "completed",
                "occurred_at": "2026-03-02T00:00:00Z",
            }
        )
        assert result == {"status": "unknown_correlation"}
        assert MarketException.objects.filter(reason="unknown_correlation").count() == 1

    def test_malformed_callback_raises(self, db, submitted):
        with pytest.raises(ValueError, match="malformed"):
            apply_callback({"correlation_id": str(submitted.correlation_id)})
        with pytest.raises(ValueError, match="malformed"):
            apply_callback(_callback(submitted, outcome="exploded"))
        assert MarketInbox.objects.count() == 0

    def test_lost_response_reconciles_then_fails(self, db, supply_point, submitted, t0):
        # One sweep: deadline expiry → reconciling → poll says unknown → failed.
        later = t0 + timedelta(seconds=31)
        client = FakeClient(gets=[{"status": "unknown", "last_seq": -1}])
        counts = sweep(client=client, now=later)
        assert counts["reconciling"] == 1
        assert counts["failed"] == 1
        submitted.refresh_from_db()
        assert submitted.state == "failed"
        assert "unknown" in submitted.detail
        supply_point.refresh_from_db()
        assert supply_point.market_state == "none"

    def test_reconcile_resolves_completed(self, db, supply_point, submitted, t0):
        later = t0 + timedelta(seconds=31)
        client = FakeClient(gets=[{"status": "completed", "last_seq": 3}])
        counts = sweep(client=client, now=later)
        assert counts["resolved"] == 1
        submitted.refresh_from_db()
        assert submitted.state == "completed"
        assert submitted.last_applied_seq == 3

    def test_reconcile_budget_exhaustion_fails(self, db, supply_point, submitted, t0):
        later = t0 + timedelta(seconds=31)
        client = FakeClient(gets=[{"status": "submitted", "last_seq": 0}])
        sweep(client=client, now=later)
        submitted.refresh_from_db()
        budget_end = submitted.reconcile_deadline_at + timedelta(seconds=1)
        sweep(client=FakeClient(), now=budget_end)
        submitted.refresh_from_db()
        assert submitted.state == "failed"


class TestSubmit:
    def test_transport_failure_retries_then_fails(self, db, supply_point, t0):
        workflow = request_transfer(supply_point, t0.date())
        client = FakeClient(posts=[MarketTransport("refused")] * 5)
        for _ in range(4):
            submit_workflow(workflow.correlation_id, client=client, now=t0)
            workflow.refresh_from_db()
            assert workflow.state == "draft"
        submit_workflow(workflow.correlation_id, client=client, now=t0)
        workflow.refresh_from_db()
        assert workflow.state == "failed"
        assert workflow.attempts == 5

    def test_lost_first_submit_is_swept(self, db, supply_point, t0):
        """If the admission task never ran, the sweep still submits."""
        workflow = request_transfer(supply_point, t0.date())
        client = FakeClient(posts=[{"status": "submitted", "seq": 0}])
        sweep(client=client, now=t0 + timedelta(seconds=10))
        workflow.refresh_from_db()
        assert workflow.state == "submitted"

    def test_digest_conflict_is_terminal(self, db, supply_point, t0):
        from taryx.core.market.client import MarketHttpError

        workflow = request_transfer(supply_point, t0.date())
        client = FakeClient(posts=[MarketHttpError(409, "digest_conflict")])
        submit_workflow(workflow.correlation_id, client=client, now=t0)
        workflow.refresh_from_db()
        assert workflow.state == "failed"
        supply_point.refresh_from_db()
        assert supply_point.market_state == "none"


class TestReviewProbes:
    """Independent-review regressions (m4-probes folded in)."""

    def test_http_failures_exhaust_to_terminal(self, db, supply_point, t0):
        """Non-409 HTTP failures count toward the attempt budget — a
        draft must not be excluded from the sweep permanently."""
        from taryx.core.market.client import MarketHttpError

        workflow = request_transfer(supply_point, t0.date())
        client = FakeClient(posts=[MarketHttpError(503, "unavailable")] * 5)
        for _ in range(5):
            submit_workflow(workflow.correlation_id, client=client, now=t0)
        sweep(client=client, now=t0 + timedelta(minutes=1))
        workflow.refresh_from_db()
        assert workflow.state == "failed"

    def test_uncertain_submit_polls_before_retry(self, db, supply_point, t0):
        """A resend after an uncertain submit polls last-known status
        first — it must not blindly post a second request."""

        class LostAck(FakeClient):
            def post(self, path, body):
                self.post_calls.append((path, body))
                raise MarketTransport("ack lost")

        workflow = request_transfer(supply_point, t0.date())
        client = LostAck(
            gets=[
                {
                    "correlation_id": str(workflow.correlation_id),
                    "status": "completed",
                    "last_seq": 1,
                }
            ]
        )
        submit_workflow(workflow.correlation_id, client=client, now=t0)
        sweep(client=client, now=t0 + timedelta(seconds=10))
        assert len(client.get_calls) >= 1
        assert len(client.post_calls) == 1

    @pytest.mark.parametrize("field,value", [("seq", 1.5), ("occurred_at", None)])
    def test_invalid_callback_cannot_complete(self, db, submitted, field, value):
        payload = _callback(submitted)
        payload[field] = value
        with pytest.raises(ValueError):
            apply_callback(payload)

    def test_terminal_callback_during_expiry_cannot_be_overwritten(
        self, db, submitted, monkeypatch
    ):
        """A callback committing between the sweep's read and its state
        change must not be overwritten by a stale in-memory state."""
        from django.db.models.query import QuerySet

        from taryx.core.market.models import TransferWorkflow

        TransferWorkflow.objects.filter(pk=submitted.pk).update(
            deadline_at=timezone.now() - timedelta(seconds=1)
        )
        original = QuerySet.__iter__
        fired = False

        def interleaved(queryset):
            nonlocal fired
            rows = original(queryset)
            if (
                not fired
                and queryset.model is TransferWorkflow
                and "deadline_at" in str(queryset.query)
            ):
                rows = iter(list(rows))
                fired = True
                apply_callback(_callback(submitted))
            return rows

        monkeypatch.setattr(QuerySet, "__iter__", interleaved)
        sweep(client=FakeClient())
        assert fired
        submitted.refresh_from_db()
        assert submitted.state == "completed"

    def test_outbox_validates_envelope(self, db, submitted):
        """A corrupt or foreign envelope must not mutate core state."""
        apply_callback(_callback(submitted))
        MarketOutbox.objects.filter(workflow=submitted).update(topic="invalid", payload={})
        drain_market_outbox()
        submitted.supply_point.refresh_from_db()
        assert submitted.supply_point.market_state != "registered"

    def test_ack_must_match_correlation(self, db, supply_point, t0):
        """An ack for a different correlation must not mark submitted."""
        workflow = request_transfer(supply_point, t0.date())
        client = FakeClient(
            posts=[{"correlation_id": str(uuid4()), "status": "submitted", "seq": 0}]
        )
        submit_workflow(workflow.correlation_id, client=client, now=t0)
        workflow.refresh_from_db()
        assert workflow.state != "submitted"

    def test_crash_after_remote_acceptance_requires_poll(self, db, supply_point, t0, monkeypatch):
        """A crash after the counterparty accepted rolls the state
        transaction back — but the durable attempt marker commits
        first, so the resend polls instead of reposting blindly."""

        class ProcessDied(BaseException):
            pass

        workflow = request_transfer(supply_point, t0.date())
        client = FakeClient(
            posts=[{"correlation_id": str(workflow.correlation_id), "status": "submitted"}],
            gets=[
                {
                    "correlation_id": str(workflow.correlation_id),
                    "status": "completed",
                    "last_seq": 1,
                }
            ],
        )

        def accepted_then_died(path, body):
            client.post_calls.append((path, body))
            raise ProcessDied()

        monkeypatch.setattr(client, "post", accepted_then_died)
        with pytest.raises(ProcessDied):
            submit_workflow(workflow.correlation_id, client=client, now=t0)
        sweep(client=client, now=t0 + timedelta(seconds=10))
        assert len(client.get_calls) == 1
        assert len(client.post_calls) == 1

    def test_recovered_terminal_at_budget_survives_crash(self, db, supply_point, t0):
        """A crash between terminal recovery and its application must
        not strand an at-budget draft — the sweep still polls it."""
        from taryx.core.market import services as s

        class ProcessDied(BaseException):
            pass

        workflow = request_transfer(supply_point, t0.date())
        workflow.attempts = 4
        workflow.save(update_fields=["attempts"])
        client = FakeClient(
            gets=[
                {
                    "correlation_id": str(workflow.correlation_id),
                    "status": "completed",
                    "last_seq": 1,
                }
            ]
            * 2
        )
        with (
            patch.object(s, "apply_callback", side_effect=ProcessDied),
            pytest.raises(ProcessDied),
        ):
            submit_workflow(workflow.correlation_id, client=client, now=t0)
        sweep(client=client, now=t0 + timedelta(seconds=10))
        workflow.refresh_from_db()
        assert workflow.state == "completed"

    def test_reconcile_missing_correlation_cannot_complete(self, db, submitted, t0):
        """A reconcile response without the workflow's correlation_id
        must not complete it — it records detail and stays reconciling."""
        from taryx.core.market.models import TransferWorkflow

        TransferWorkflow.objects.filter(pk=submitted.pk).update(
            state="reconciling",
            reconcile_deadline_at=t0 + timedelta(minutes=1),
        )
        client = FakeClient()
        client.get = lambda path: {"status": "completed", "last_seq": 1}
        sweep(client=client, now=t0 + timedelta(seconds=31))
        submitted.refresh_from_db()
        assert submitted.state == "reconciling"

    @pytest.mark.parametrize("raw", [b"[]", b"null", b'"submitted"'])
    def test_transport_rejects_nonobject_json(self, raw):
        from unittest.mock import patch

        from taryx.core.market.client import MarketClient, MarketMalformed

        with (
            patch("urllib.request.urlopen", return_value=io.BytesIO(raw)),
            pytest.raises(MarketMalformed),
        ):
            MarketClient("http://unused", "token").get("/transfers/unused")

    @pytest.mark.parametrize(
        "field,value",
        [("effective_date", "wrong-date"), ("occurred_at", "not-a-timestamp")],
    )
    def test_outbox_rejects_invalid_contract_fields(self, db, submitted, field, value):
        apply_callback(_callback(submitted))
        event = MarketOutbox.objects.get(workflow=submitted)
        event.payload[field] = value
        event.save(update_fields=["payload"])
        assert drain_market_outbox() == 0
        event.refresh_from_db()
        assert event.delivered_at is None

    def test_core_consumer_rejects_missing_schema_fields(self, db, submitted):
        from taryx.core.accounts.services import apply_transfer_outcome

        with pytest.raises(ValueError):
            apply_transfer_outcome(
                submitted.supply_point,
                {"version": "1", "nmi": submitted.supply_point.nmi},
            )

    def test_stale_outbox_delivery_does_not_reapply_old_correlation(
        self, db, submitted, monkeypatch, t0
    ):
        """A delivered event replayed after a newer transfer is pending
        must not register the point — the pending correlation wins."""
        from django.db.models.query import QuerySet

        apply_callback(_callback(submitted))
        original = QuerySet.__iter__
        interleaved = False

        def competing_drain(queryset):
            nonlocal interleaved
            rows = original(queryset)
            if queryset.model is MarketOutbox and not interleaved:
                rows = iter(list(rows))
                interleaved = True
                assert drain_market_outbox() == 1
                request_transfer(submitted.supply_point, t0.date())
                submitted.supply_point.refresh_from_db()
                assert submitted.supply_point.market_state == "pending"
            return rows

        monkeypatch.setattr(QuerySet, "__iter__", competing_drain)
        drain_market_outbox()
        submitted.supply_point.refresh_from_db()
        assert submitted.supply_point.market_state == "pending"
        # The stale event stays undeliverable — visible, not silently ok.
        event = MarketOutbox.objects.get(workflow=submitted)
        assert event.attempts > 0

    def test_one_attempt_budget_allows_initial_submission(self, db, supply_point, t0, settings):
        """The first marker must not consume the whole budget before
        the first POST — max_attempts counts posts, not markers."""
        settings.MARKET_MAX_ATTEMPTS = 1
        workflow = request_transfer(supply_point, t0.date())
        client = FakeClient(posts=[{"status": "submitted", "seq": 0}])
        submit_workflow(workflow.correlation_id, client=client, now=t0)
        assert len(client.post_calls) == 1
        workflow.refresh_from_db()
        assert workflow.state == "submitted"

    def test_boolean_recovery_sequence_cannot_abort_sweep(self, db, supply_point, t0):
        """A boolean last_seq must fail recovery validation, not escape
        into apply_callback and abort the whole sweep."""
        workflow = request_transfer(supply_point, t0.date())
        workflow.attempts = 1
        workflow.save(update_fields=["attempts"])
        client = FakeClient(
            posts=[{"status": "submitted", "seq": 0}],
            gets=[
                {
                    "correlation_id": str(workflow.correlation_id),
                    "status": "completed",
                    "last_seq": True,
                }
            ],
        )
        sweep(client=client, now=t0 + timedelta(seconds=10))
        workflow.refresh_from_db()
        assert workflow.state != "completed"


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    return urllib.request.urlopen(req, timeout=5).status


class _CallbackSink(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            _CallbackSink.received.append(json.loads(raw))
        except ValueError:
            _CallbackSink.received.append({"_raw": raw.decode("utf-8", "replace")})
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


@pytest.fixture
def sim(tmp_path):
    sim_port, cb_port = _free_port(), _free_port()
    _CallbackSink.received = []
    sink = ThreadingHTTPServer(("127.0.0.1", cb_port), _CallbackSink)
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(SIM),
            "--port",
            str(sim_port),
            "--db",
            str(tmp_path / "market.db"),
            "--token",
            "test-token",
        ]
    )
    try:
        base = f"http://localhost:{sim_port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{base}/healthz", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("market-sim did not become healthy")
        yield base, f"http://localhost:{cb_port}/cb"
    finally:
        proc.kill()
        sink.shutdown()


class TestRealSimulator:
    """The wire contract against the actual coordinator subprocess."""

    def test_submit_ack_idempotent_and_409(self, db, supply_point, sim, t0):
        base, _ = sim
        client = MarketClient(base, "test-token")
        workflow = request_transfer(supply_point, t0.date())
        submit_workflow(workflow.correlation_id, client=client, now=t0)
        workflow.refresh_from_db()
        assert workflow.state == "submitted"
        # Idempotent resubmission: same correlation/digest → same ack.
        again = client.post(
            "/transfers",
            {
                "correlation_id": str(workflow.correlation_id),
                "nmi": supply_point.nmi,
                "effective_date": t0.date().isoformat(),
                "request_digest": workflow.request_digest,
            },
        )
        assert again["status"] == "submitted"
        # Same correlation, different digest → 409.
        with pytest.raises(Exception, match="409"):
            client.post(
                "/transfers",
                {
                    "correlation_id": str(workflow.correlation_id),
                    "nmi": supply_point.nmi,
                    "effective_date": t0.date().isoformat(),
                    "request_digest": "0" * 64,
                },
            )

    @override_settings(MARKET_CALLBACK_URL="")
    def test_happy_callback_over_http(self, db, supply_point, sim, t0):
        base, cb_url = sim
        _post(f"{base}/_admin/scenario", {"name": "happy", "delay": 0.1})
        client = MarketClient(base, "test-token")
        workflow = request_transfer(supply_point, t0.date())
        body = {
            "correlation_id": str(workflow.correlation_id),
            "nmi": supply_point.nmi,
            "effective_date": t0.date().isoformat(),
            "request_digest": workflow.request_digest,
            "callback_url": cb_url,
        }
        client.post("/transfers", body)
        deadline = time.time() + 5
        while time.time() < deadline and not _CallbackSink.received:
            time.sleep(0.05)
        assert len(_CallbackSink.received) == 1
        result = apply_callback(_CallbackSink.received[0])
        assert result == {"status": "completed"}
        # The coordinator's own last-known status agrees.
        poll = client.get(f"/transfers/{workflow.correlation_id}")
        assert poll["status"] == "completed"

    def test_fault_scripts_emit_expected_deliveries(self, db, supply_point, sim, t0):
        """Each named scenario produces its scripted callback pattern —
        the scripts are deterministic inputs to the adapter tests."""
        base, cb_url = sim
        client = MarketClient(base, "test-token")

        def run(scenario, expected=1, delay=0.1):
            _CallbackSink.received = []
            _post(f"{base}/_admin/scenario", {"name": scenario, "delay": delay})
            workflow = request_transfer(supply_point, t0.date())
            client.post(
                "/transfers",
                {
                    "correlation_id": str(workflow.correlation_id),
                    "nmi": supply_point.nmi,
                    "effective_date": t0.date().isoformat(),
                    "request_digest": workflow.request_digest,
                    "callback_url": cb_url,
                },
            )
            deadline = time.time() + 5
            while time.time() < deadline and len(_CallbackSink.received) < expected:
                time.sleep(0.05)
            return _CallbackSink.received

        assert [c["outcome"] for c in run("business-reject")] == ["rejected"]
        assert [c["seq"] for c in run("duplicate-callback", expected=2)] == [1, 1]
        assert [c["seq"] for c in run("out-of-order-callback", expected=2)] == [2, 1]
        assert "_raw" in run("malformed-callback")[0]

    def test_unauthorised_and_version_rejected(self, sim):
        base, _ = sim
        for headers, want in (
            ({}, 400),
            ({"taryx-market-version": "1"}, 401),
        ):
            req = urllib.request.Request(
                f"{base}/transfers",
                data=b"{}",
                headers={"Content-Type": "application/json", **headers},
            )
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("expected HTTP error")
            except urllib.error.HTTPError as exc:
                assert exc.code == want


class TestCallbackEndpoint:
    """The HTTP ingress itself: auth, version, malformed parking."""

    def test_requires_bearer_and_version(self, db):
        client = HttpClient()
        assert (
            client.post("/callbacks/transfers", "{}", content_type="application/json").status_code
            == 400
        )
        assert (
            client.post(
                "/callbacks/transfers",
                "{}",
                content_type="application/json",
                headers={"taryx-market-version": "1"},
            ).status_code
            == 401
        )

    def test_malformed_parked_as_exception(self, db):
        client = HttpClient()
        response = client.post(
            "/callbacks/transfers",
            "{not json",
            content_type="application/json",
            headers={
                "taryx-market-version": "1",
                "Authorization": "Bearer taryx-market-token",
            },
        )
        assert response.status_code == 400
        assert MarketException.objects.filter(reason="malformed").exists()

    def test_valid_callback_flows(self, db, submitted):
        client = HttpClient()
        response = client.post(
            "/callbacks/transfers",
            json.dumps(_callback(submitted)),
            content_type="application/json",
            headers={
                "taryx-market-version": "1",
                "Authorization": "Bearer taryx-market-token",
            },
        )
        assert response.status_code == 200
        assert response.json() == {"status": "completed"}
