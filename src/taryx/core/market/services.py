"""Transfer workflow services — the decision-005 transition table.

Draft submits are kicked by the admission path; retries, deadlines and
reconciliation are driven by the periodic `sweep` so a crash mid-flow
always resumes from durable state. Callbacks dedup on
(correlation_id, seq) in the inbox before any state moves.
"""

import hashlib
import json
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

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
        supply_point.market_state = SupplyPoint.MarketState.PENDING
        supply_point.save(update_fields=["market_state"])
    return workflow


def _fail(workflow: TransferWorkflow, detail: str) -> TransferWorkflow:
    workflow.state = State.FAILED
    workflow.detail = detail[:500]
    workflow.save()
    _clear_pending(workflow.supply_point)
    return workflow


def _clear_pending(supply_point: SupplyPoint) -> None:
    if supply_point.market_state == SupplyPoint.MarketState.PENDING:
        supply_point.market_state = SupplyPoint.MarketState.NONE
        supply_point.save(update_fields=["market_state"])


def submit_workflow(correlation_id, *, client=None, now=None) -> TransferWorkflow:
    """Send (or resend) the durable request. Idempotent: the coordinator
    dedups on correlation_id, so a retry after an uncertain submit is
    safe. 409 means the same correlation carries a different digest —
    a caller bug, terminal."""
    client = client or _client()
    now = now or timezone.now()
    conf = _conf()
    with transaction.atomic():
        workflow = TransferWorkflow.objects.select_for_update().get(correlation_id=correlation_id)
        if workflow.state != State.DRAFT:
            return workflow
        workflow.attempts += 1
        try:
            response = client.post("/transfers", _request_body(workflow))
        except MarketTransport as exc:
            workflow.detail = str(exc)[:500]
            if workflow.attempts >= conf["max_attempts"]:
                return _fail(workflow, f"submit attempts exhausted: {exc}")
            workflow.save()
            return workflow
        except MarketHttpError as exc:
            if exc.status == 409:
                return _fail(workflow, f"digest conflict under same correlation: {exc}")
            workflow.detail = str(exc)[:500]
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
        if response.get("status") != "submitted":
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
        seq = int(payload["seq"])
        outcome = str(payload["outcome"])
        occurred_at = str(payload["occurred_at"])
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

    drafts = TransferWorkflow.objects.filter(
        state=State.DRAFT,
        attempts__lt=conf["max_attempts"],
        updated_at__lte=now - conf["retry_after"],
    ).values_list("correlation_id", flat=True)
    for correlation_id in drafts:
        workflow = submit_workflow(correlation_id, client=client, now=now)
        counts["retried"] += workflow.state == State.SUBMITTED

    expired = TransferWorkflow.objects.filter(state=State.SUBMITTED, deadline_at__lt=now)
    for workflow in expired:
        workflow.state = State.RECONCILING
        workflow.reconcile_deadline_at = now + conf["reconcile_budget"]
        workflow.save()
        counts["reconciling"] += 1

    ids = list(
        TransferWorkflow.objects.filter(state=State.RECONCILING).values_list("pk", flat=True)
    )
    for pk in ids:
        with transaction.atomic():
            workflow = TransferWorkflow.objects.select_for_update().get(pk=pk)
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
            workflow.last_counterparty_status = status
            workflow.save()
        if status in OUTCOMES:
            result = apply_callback(
                {
                    "correlation_id": str(workflow.correlation_id),
                    "seq": int(response.get("last_seq", 0)),
                    "outcome": status,
                    "occurred_at": now.isoformat(),
                },
                now=now,
            )
            counts["resolved"] += result["status"] in OUTCOMES
        elif status == "unknown":
            with transaction.atomic():
                workflow = TransferWorkflow.objects.select_for_update().get(pk=pk)
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
                if (
                    workflow.state == State.COMPLETED
                    and supply_point.market_state != SupplyPoint.MarketState.REGISTERED
                ):
                    supply_point.market_state = SupplyPoint.MarketState.REGISTERED
                    supply_point.save(update_fields=["market_state"])
                event.delivered_at = now
                event.save(update_fields=["delivered_at"])
                delivered += 1
        except Exception as exc:
            event.attempts += 1
            event.last_error = str(exc)[:500]
            event.save(update_fields=["attempts", "last_error"])
    return delivered
