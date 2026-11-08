# 005 — Bounded market workflow contract (synthetic)

Date: 2026-11-08
Status: Accepted (resolves BLK-002)
Acceptance source: BLK-002 delegates the scenario selection and protocol definition to the implementing agent, requiring a clearly synthetic protocol unless a sourced standard subset is used. This document freezes that contract for TAR-015.

## Context

TAR-014 requires one asynchronous supply-point interaction with durable adapter state, correlation, deduplication and reconciliation. No real AEMO procedure is claimed: the protocol below is a Taryx simulation (`taryx-market/1`) and must be labelled as such wherever it appears. Nothing here asserts MSATS/aseXML conformance, cooling-off periods or objection windows.

## Scenario

**Supply-point transfer request.** A client deployment (the gaining retailer) asks a counterparty market coordinator to register a NMI transfer into its portfolio. The request is submitted once, acknowledged synchronously, and resolved asynchronously by outcome callbacks. The simulator plays the coordinator.

## Protocol: `taryx-market/1` (synthetic, JSON/HTTP)

Transport rules:

- Every request carries `taryx-market-version: 1`, `Authorization: Bearer <configured token>` (synthetic static credential per deployment) and a `correlation_id` (UUIDv4, generated at admission, immutable for the life of the workflow).
- Version mismatch, missing/invalid token or malformed JSON are rejected at ingress (`400`/`401`) with no workflow state change.
- Content is JSON; all amounts/ids are strings or ISO-8601 datetimes.

Messages:

| Message | Direction | Shape (v1) | Notes |
| --- | --- | --- | --- |
| `POST /transfers` | adapter → coordinator | `{correlation_id, nmi, effective_date, request_digest, callback_url?}` | Idempotent submit: the coordinator dedups on `correlation_id`; a retried submit returns the same ack, never a second workflow. `request_digest` is sha256 of `{correlation_id, nmi, effective_date}` — a resubmission with a different digest under the same correlation is a `409` conflict. `callback_url` is optional simulator plumbing (falls back to a configured default); it is delivery routing, not part of the signed digest. |
| `transfer.ack` | synchronous response | `{correlation_id, status: "submitted", seq: 0}` | Transport-level ack only. |
| `POST /callbacks/transfers` | coordinator → adapter | `{correlation_id, seq, outcome, occurred_at, detail?}` | `outcome ∈ {completed, rejected}`; `seq` is a strictly increasing counterparty-side sequence per correlation. |
| `GET /transfers/{correlation_id}` | adapter → coordinator | → `{correlation_id, status, last_seq}` | Reconciliation poll: returns the coordinator's last-known status (`submitted`, `completed`, `rejected`) without inventing an outcome. |

## Workflow states

`draft → submitted → (completed | rejected)`, plus two failure states:

- `reconciling` — a submitted workflow past its outcome deadline; the adapter polls `GET /transfers/{correlation_id}` rather than resubmitting.
- `failed` — adapter-side terminal: reconciliation exhausted with counterparty `unknown`, or unrecoverable submission failure after the bounded retry budget. A failed workflow is never silently retried; a new business attempt is an explicitly new operation with a new correlation_id.

## Frozen transition table

| Current state | Event | Result |
| --- | --- | --- |
| draft | submit accepted (ack) | → submitted (deadline armed) |
| draft | submit transport failure | bounded retry (same correlation_id/digest); budget exhausted → failed |
| draft | submit 409 digest conflict | → failed (caller bug: same correlation, different request) |
| submitted | callback `completed`, seq > last_applied | → completed; publish outcome to core via outbox |
| submitted | callback `rejected`, seq > last_applied | → rejected (terminal; no core effect beyond the record) |
| submitted | callback with seq ≤ last_applied | duplicate — 200 ack, no transition |
| submitted | outcome deadline reached | → reconciling (poll last-known status) |
| reconciling | poll returns completed/rejected | apply as the matching callback |
| reconciling | poll returns submitted | reschedule poll within reconcile budget |
| reconciling | poll returns unknown / budget exhausted | → failed |
| submitted/reconciling | callback arrives after terminal apply | late event — recorded, cannot overwrite the terminal state |
| any | unknown correlation_id | exception inbox entry, no state change, visible to operators |
| any | malformed callback (schema fail) | 400, no state change, counted |
| completed/rejected/failed | any further callback | recorded as late/duplicate; terminal state wins |

Out-of-order delivery is defined by `seq`: only `seq > last_applied_seq` may transition; equal-or-lower is a duplicate/late event regardless of arrival order.

## Core interaction

The adapter (a new core module) owns durable workflow state, the inbound inbox and outbound outbox rows. It **never writes billing/account tables directly**. A terminal `completed` outcome publishes a versioned `market.transfer_completed` outbox event that core validates (schema + version + signature fields) and deduplicates before recording the transfer outcome on the supply point — one business transition per correlation, however many callbacks arrive.

## Durability and recovery

- Workflow row, inbox rows `(correlation_id, seq)` unique, and outbox rows commit transactionally; no outcome is applied before it is durable.
- Restart resumes from durable state: `reconciling` workflows re-arm their poll; in-flight submits re-check `GET /transfers/{correlation_id}` before deciding retry vs reconcile.
- Persist per workflow: correlation_id, request digest, state, last_applied_seq, attempt count, deadline, last counterparty status.
- Counterparty unavailability affects only the market path; billing, ingestion and the API stay responsive.

## Fault scripts (simulator, deterministic from a seed)

The coordinator simulator replays named scenarios: `happy`, `duplicate-callback`, `out-of-order-callback`, `late-completion`, `business-reject`, `lost-response` (ack then silence → reconcile), `unknown-correlation`, `malformed-callback`, `unavailable` (connection refused/timeout windows). Each script is fixed — the same seed produces the same timing and outcomes — so tests and reviewers can replay it independently.

## Consequences and follow-up

- TAR-015 implements: the coordinator simulator (own service, like legacy-sim), the adapter module with the table above, inbox/outbox wiring and the fault-script tests.
- Real protocol research (MSATS/aseXML subset) remains a possible later milestone; until a sourced subset exists, every artefact is labelled `taryx-market/1` synthetic.
- Deviating from a transition in the table requires amending this decision record first.
