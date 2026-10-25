# 004 — Operator GraphQL contract, session auth and roles

Date: 2026-10-25
Status: Accepted
Acceptance source: The operator contract requires a frozen query/mutation/error shape, operation polling, a chosen session mechanism and enforced roles; the specific shapes are design selections within delegated planning authority.

## Context

TAR-009 exposes ingestion, rating, billing, correction and quarantine review to a browser portal. Long-running mutations must return operation identities the portal can poll; unknown outcomes must reuse the same idempotency key rather than invite a duplicate financial operation. Permissions and audit must be enforced server-side.

## Decision

**Transport.** Django session authentication over the existing `/graphql` endpoint; CSRF is enforced (the view is no longer csrf_exempt) via the standard `csrftoken` cookie + `X-CSRFToken` header pair. The Vite dev proxy keeps the portal same-origin. Login/logout are GraphQL mutations; `me` exposes the current identity and role.

**Roles.** Three seeded groups: `viewer` (queries only), `operator` (viewer + ingest/rate/bill mutations), `approver` (viewer + quarantine resolution). Resolvers check group membership server-side; anonymous and insufficient roles fail with a `permission_denied` error. Seed users are development identities only (`viewer`/`operator`/`approver`, documented passwords, no real PII).

**Query surface.** Bounded, paginated-by-limit queries only: `accounts`, `account(reference)` with channels, `ingestionBatches`, `quarantinedIntervals`, `currentIntervals(channelId, day)`, `ratingRuns`, `invoice(number)` with lines/journals/adjustments, `billingOperation(operationId)`. No unbounded list fields.

**Mutation surface and errors.** `login`, `logout`, `ingestNem12(filename, content)`, `rateAccount(reference, periodStart, periodEnd)`, `billAccount(reference, periodStart, periodEnd, operationId)`, `resolveQuarantine(quarantineId, recordId, reason)`. Mutations return a payload object `{ok, code, message, ...}`; domain failures are stable `code` values (`incomplete_coverage`, `operation_conflict`, `stale`, `not_found`, `permission_denied`, ...), not thrown GraphQL errors, so the portal can render them deterministically.

**Operation polling.** `billAccount` admits durably and returns the operation ID plus current status; the portal polls `billingOperation` until `complete`/`stale`/`failed`. Retries and refreshes reuse the caller's operation ID, which is the admission idempotency key — an interrupted or timed-out journey resumes the same outcome instead of duplicating it. ingest/rate are synchronous and return their result directly.

**Audit.** Every consequential mutation (ingest, rate, bill, resolve) writes an `AuditEntry` (actor, action, target, payload digest, result) inside the action's transaction where applicable.

## Alternatives

Token/JWT auth adds machinery without benefit for a same-origin local portal. Field-level GraphQL errors were rejected because transport-level errors cannot carry stable domain codes. Exposing file uploads via multipart was rejected in favour of a text `content` field — NEM12 fixtures are small and it avoids an extra dependency.

## Consequences and follow-up

Single-process session auth is sufficient for the demo; multi-instance deployments would need a shared session backend. Approver mutation scope is quarantine resolution only; cohort routing arrives with TAR-012. GraphQL depth/cost limits are not enforced beyond bounded lists — a documented limitation for the demo contract.
