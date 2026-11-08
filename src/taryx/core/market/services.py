"""Transfer workflow services — the decision-005 transition table.

Draft submits are kicked by the admission path; retries, deadlines and
reconciliation are driven by the periodic `sweep` so a crash mid-flow
always resumes from durable state. Callbacks dedup on
(correlation_id, seq) in the inbox before any state moves.
"""

import hashlib
import json
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from taryx.core.accounts import services as account_services
from taryx.core.accounts.models import SupplyPoint
from taryx.core.market.client import (
    MarketClient,
    MarketHttpError,
    MarketMalformed,
    MarketTransport,
)
from taryx.core.market.models import (
    TERMINAL_STATES,
    MarketException,
    MarketInbox,
    MarketOutbox,
    TransferWorkflow,
)

OUTCOMES = {"completed", "rejected"}
State = TransferWorkflow.State


def _conf() -> dict:
    return {
        "outcome_deadline": timedelta(seconds=settings.MARKET_OUTCOME_DEADLINE_SECONDS),
        "reconcile_budget": timedelta(seconds=settings.MARKET_RECONCILE_BUDGET_SECONDS),
        "max_attempts": settings.MARKET_MAX_ATTEMPTS,
        "retry_after": timedelta(seconds=settings.MARKET_RETRY_SECONDS),
    }


def _client() -> MarketClient:
    return MarketClient(settings.MARKET_BASE_URL, settings.MARKET_TOKEN)


def _request_fields(workflow: TransferWorkflow) -> dict:
    return {
        "correlation_id": str(workflow.correlation_id),
        "nmi": workflow.supply_point.nmi,
        "effective_date": workflow.effective_date.isoformat(),
    }


def _request_body(workflow: TransferWorkflow) -> dict:
    body = {
        **_request_fields(workflow),
        "request_digest": workflow.request_digest,
    }
    if settings.MARKET_CALLBACK_URL:
        body["callback_url"] = settings.MARKET_CALLBACK_URL
    return body


def request_transfer(supply_point: SupplyPoint, effective_date) -> TransferWorkflow:
    """Admit a new transfer workflow durably; the caller kicks
    `market.submit`. The supply point moves to `pending` in the same
    transaction so the request is visible before any network call."""
    with transaction.atomic():
        workflow = TransferWorkflow.objects.create(
            supply_point=supply_point, effective_date=effective_date
        )
        workflow.request_digest = hashlib.sha256(
            json.dumps(_request_fields(workflow), sort_keys=True).encode()
        ).hexdigest()
        workflow.save(update_fields=["request_digest"])
        account_services.begin_transfer(supply_point, workflow.correlation_id)
    return workflow


def _fail(workflow: TransferWorkflow, detail: str) -> TransferWorkflow:
    workflow.state = State.FAILED
    workflow.detail = detail[:500]
    workflow.save()
    account_services.clear_pending_transfer(workflow.supply_point)
    return workflow


def _clear_pending(supply_point: SupplyPoint) -> None:
    account_services.clear_pending_transfer(supply_point)


def submit_workflow(correlation_id, *, client=None, now=None) -> TransferWorkflow:
    """Send (or resend) the durable request. Idempotent: the coordinator
    dedups on correlation_id, so a retry after an uncertain submit is
    safe — but a resend first polls last-known status so a lost ack
    never causes a blind duplicate. 409 means the same correlation
    carries a different digest — a caller bug, terminal."""
    client = client or _client()
    now = now or timezone.now()
    conf = _conf()
    # Durable intent marker BEFORE the network call: a crash after the
    # counterparty accepted but before the state transaction commits
    # must still leave evidence that a request may be in flight, so the
    # next attempt polls instead of trusting a rolled-back counter.
    marked = TransferWorkflow.objects.filter(
        correlation_id=correlation_id, state=State.DRAFT
    ).update(attempts=F("attempts") + 1)
    if not marked:
        return TransferWorkflow.objects.get(correlation_id=correlation_id)
    recovered = None
    with transaction.atomic():
        workflow = TransferWorkflow.objects.select_for_update().get(correlation_id=correlation_id)
        if workflow.state != State.DRAFT:
            return workflow
        if workflow.attempts > 1:
            # Uncertain submit: ask the counterparty for last-known
            # status before resending (decision 005 recovery).
            try:
                polled = client.get(f"/transfers/{correlation_id}")
            except (MarketTransport, MarketHttpError, MarketMalformed):
                polled = None
            if polled and str(polled.get("correlation_id")) == str(correlation_id):
                status = str(polled.get("status"))
                last_seq = polled.get("last_seq")
                if (
                    status in OUTCOMES
                    and isinstance(last_seq, int)
                    and not isinstance(last_seq, bool)
                    and last_seq >= 0
                ):
                    recovered = {"seq": last_seq, "outcome": status}
                    workflow.detail = "recovered via status poll"
                    workflow.save()
                elif status == "submitted":
                    # The lost ack was accepted — arm the outcome
                    # deadline instead of resubmitting.
                    workflow.state = State.SUBMITTED
                    workflow.deadline_at = now + conf["outcome_deadline"]
                    workflow.last_counterparty_status = "submitted"
                    workflow.detail = "recovered via status poll"
                    workflow.save()
                    return workflow
        if recovered is None:
            if workflow.attempts > conf["max_attempts"]:
                return _fail(workflow, "submit attempts exhausted")
            try:
                response = client.post("/transfers", _request_body(workflow))
            except (MarketTransport, MarketHttpError) as exc:
                if isinstance(exc, MarketHttpError) and exc.status == 409:
                    return _fail(workflow, f"digest conflict under same correlation: {exc}")
                workflow.detail = str(exc)[:500]
                if workflow.attempts >= conf["max_attempts"]:
                    return _fail(workflow, f"submit attempts exhausted: {exc}")
                workflow.save()
                return workflow
            except MarketMalformed as exc:
                # Malformed ack — outcome uncertain; reconcile asks the
                # counterparty for last-known status instead of resubmitting.
                workflow.state = State.RECONCILING
                workflow.reconcile_deadline_at = now + conf["reconcile_budget"]
                workflow.detail = f"malformed ack: {exc}"
                workflow.save()
                return workflow
            if response.get("status") != "submitted" or str(response.get("correlation_id")) != str(
                correlation_id
            ):
                workflow.state = State.RECONCILING
                workflow.reconcile_deadline_at = now + conf["reconcile_budget"]
                workflow.detail = f"unexpected ack: {response!r}"[:500]
                workflow.save()
                return workflow
            workflow.state = State.SUBMITTED
            workflow.deadline_at = now + conf["outcome_deadline"]
            workflow.last_counterparty_status = "submitted"
            workflow.detail = ""
            workflow.save()
    if recovered is not None:
        apply_callback(
            {
                "correlation_id": str(correlation_id),
                "seq": recovered["seq"],
                "outcome": recovered["outcome"],
                "occurred_at": now.isoformat(),
            },
            now=now,
        )
        return TransferWorkflow.objects.get(correlation_id=correlation_id)
    return workflow


def apply_callback(payload: dict, *, now=None) -> dict:
    """Apply one inbound callback through the frozen transition table.

    Returns the ack status for the HTTP layer; raises ValueError on a
    schema-invalid payload (the view maps it to 400). Unknown
    correlations are parked as exceptions, never silently dropped.
    """
    now = now or timezone.now()
    try:
        correlation_id = UUID(str(payload["correlation_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed callback: {exc}") from exc
    seq = payload.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        raise ValueError(f"malformed callback: seq {seq!r}")
    try:
        outcome = str(payload["outcome"])
        occurred_at = datetime.fromisoformat(str(payload["occurred_at"])).isoformat()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed callback: {exc}") from exc
    if outcome not in OUTCOMES:
        raise ValueError(f"malformed callback: outcome {outcome!r}")

    workflow = TransferWorkflow.objects.filter(correlation_id=correlation_id).first()
    if workflow is None:
        MarketException.objects.create(
            correlation_id=correlation_id,
            reason="unknown_correlation",
            raw=json.dumps(payload),
        )
        return {"status": "unknown_correlation"}

    with transaction.atomic():
        workflow = TransferWorkflow.objects.select_for_update().get(pk=workflow.pk)
        note = "applied"
        if workflow.state in TERMINAL_STATES:
            note = "late"
        elif seq <= workflow.last_applied_seq:
            note = "duplicate"
        try:
            with transaction.atomic():  # savepoint: dedup conflict rolls back cleanly
                MarketInbox.objects.create(
                    workflow=workflow,
                    correlation_id=correlation_id,
                    seq=seq,
                    outcome=outcome,
                    payload=payload,
                    note=note,
                )
        except IntegrityError:
            return {"status": "duplicate"}
        if note != "applied":
            return {"status": note}
        workflow.last_applied_seq = seq
        workflow.last_counterparty_status = outcome
        workflow.state = State.COMPLETED if outcome == "completed" else State.REJECTED
        workflow.save()
        if outcome == "completed":
            MarketOutbox.objects.create(
                workflow=workflow,
                payload={
                    "version": "1",
                    "correlation_id": str(correlation_id),
                    "nmi": workflow.supply_point.nmi,
                    "effective_date": workflow.effective_date.isoformat(),
                    "occurred_at": occurred_at,
                },
            )
        else:
            _clear_pending(workflow.supply_point)
    return {"status": outcome}


def sweep(*, client=None, now=None) -> dict:
    """Periodic driver: retry draft submits, arm reconciliation on
    deadline expiry and poll last-known counterparty status. Bounded;
    never invents an outcome."""
    client = client or _client()
    now = now or timezone.now()
    conf = _conf()
    counts = {"retried": 0, "reconciling": 0, "resolved": 0, "failed": 0}

    # At-cap drafts are included: submit polls last-known status first,
    # so a stranded draft still recovers a terminal outcome instead of
    # failing blind — and exhausts only when nothing comes back.
    drafts = TransferWorkflow.objects.filter(
        state=State.DRAFT,
        updated_at__lte=now - conf["retry_after"],
    ).values_list("correlation_id", flat=True)
    for correlation_id in drafts:
        workflow = submit_workflow(correlation_id, client=client, now=now)
        counts["retried"] += workflow.state == State.SUBMITTED

    expired = TransferWorkflow.objects.filter(state=State.SUBMITTED, deadline_at__lt=now)
    for workflow in expired:
        # State-guarded update: a callback that committed after this row
        # was read must not be overwritten by a stale in-memory state.
        counts["reconciling"] += TransferWorkflow.objects.filter(
            pk=workflow.pk, state=State.SUBMITTED
        ).update(
            state=State.RECONCILING,
            reconcile_deadline_at=now + conf["reconcile_budget"],
        )

    ids = list(
        TransferWorkflow.objects.filter(state=State.RECONCILING).values_list("pk", flat=True)
    )
    for pk in ids:
        with transaction.atomic():
            workflow = TransferWorkflow.objects.select_for_update().get(pk=pk)
            if workflow.state != State.RECONCILING:
                continue
            if workflow.reconcile_deadline_at and workflow.reconcile_deadline_at < now:
                _fail(workflow, "reconcile budget exhausted")
                counts["failed"] += 1
                continue
            try:
                response = client.get(f"/transfers/{workflow.correlation_id}")
            except (MarketTransport, MarketHttpError, MarketMalformed) as exc:
                workflow.detail = str(exc)[:500]
                workflow.save()
                continue
            status = str(response.get("status"))
            if str(response.get("correlation_id")) != str(workflow.correlation_id):
                workflow.detail = "reconcile response missing or wrong correlation"
                workflow.save()
                continue
            workflow.last_counterparty_status = status
            workflow.save()
        last_seq = response.get("last_seq")
        if (
            status in OUTCOMES
            and isinstance(last_seq, int)
            and not isinstance(last_seq, bool)
            and last_seq >= 0
        ):
            result = apply_callback(
                {
                    "correlation_id": str(workflow.correlation_id),
                    "seq": last_seq,
                    "outcome": status,
                    "occurred_at": now.isoformat(),
                },
                now=now,
            )
            counts["resolved"] += result["status"] in OUTCOMES
        elif status == "unknown":
            with transaction.atomic():
                workflow = TransferWorkflow.objects.select_for_update().get(pk=pk)
                if workflow.state == State.RECONCILING:
                    _fail(workflow, "counterparty reports unknown correlation")
                    counts["failed"] += 1
    return counts


def drain_market_outbox(*, now=None) -> int:
    """Deliver pending market outcomes. Each event is its own
    transaction: the supply-point update and delivered_at commit
    together; one failing event cannot starve later ones forever."""
    now = now or timezone.now()
    delivered = 0
    pending = MarketOutbox.objects.filter(delivered_at__isnull=True).order_by(
        "attempts", "created_at"
    )
    for event in pending:
        try:
            with transaction.atomic():
                workflow = event.workflow
                supply_point = workflow.supply_point
                payload = event.payload
                try:
                    occurred_ok = bool(datetime.fromisoformat(str(payload["occurred_at"])))
                except (TypeError, ValueError):
                    occurred_ok = False
                if (
                    event.topic != "market.transfer_completed"
                    or payload.get("correlation_id") != str(workflow.correlation_id)
                    or payload.get("effective_date") != workflow.effective_date.isoformat()
                    or not occurred_ok
                ):
                    raise ValueError("invalid outcome envelope")
                if workflow.state == State.COMPLETED:
                    # The validating core consumer owns the mutation —
                    # it verifies the envelope's signature fields
                    # (version, nmi) against the supply point.
                    account_services.apply_transfer_outcome(supply_point, payload)
                event.delivered_at = now
                event.save(update_fields=["delivered_at"])
                delivered += 1
        except Exception as exc:
            event.attempts += 1
            event.last_error = str(exc)[:500]
            event.save(update_fields=["attempts", "last_error"])
    return delivered
