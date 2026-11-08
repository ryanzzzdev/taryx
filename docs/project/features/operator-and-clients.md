# Operator portal and client isolation

Date: 2026-10-25
Status: TAR-009 slice implemented and re-verified after independent-review remediation (decision 004 contract: session auth, roles, bounded GraphQL, operation polling, audit, portal journey, CSRF origin bootstrap, durable browser operation IDs). Client isolation remains planning contract.
Re-review at `de0e08d`: rating snapshot/membership and browser account-recovery claims above are only partially verified; see [remaining findings](../evidence/m2-independent-review.md). M2 remains open.
Tasks: [TAR-009](../backlog.md#tar-009), [TAR-012](../backlog.md#tar-012), [TAR-013](../backlog.md#tar-013).

2026-11-08: TAR-009 reopened by [foundation re-review F3](../evidence/m1-independent-review.md): invoice totals and ledger legs are visible, but the required pinned line-item explanation is absent; round 2 confirmed new-engine lines but not authoritative legacy evidence. Remediated same day — issued documents expand into the pinned *authoritative* calculation's line items (tariff, segment, quantity, rate, amount, basis; `calculationSource` distinguishes the engine), reconciling to the invoice total for both engines.

Round-three review at `e809640` found persisted-line rendering and mutable pinned evidence gaps (F3/F4); remediated same day — real legacy lines render and the pinned LegacyCalculation is immutable at the database level. [Review](../evidence/m1-independent-review.md).

## Operator journeys

The portal supports account/supply-point inspection, ingestion status and rejected data, bill/line-item provenance, original and revised liability, operation recovery, comparison reports and cohort cutover. Introduce these screens with their backend milestones rather than leaving all UI integration until the end.

Long-running mutations return an operation ID; the portal displays queued, running, failed, stale and successful outcomes with recovery guidance. Browser retries and refreshes recover from durable state. A timed-out request must not be presented as a definite failure or invite a duplicate financial operation. Use the same idempotency key when the outcome is unknown.

Queries are paginated and bounded. Changes carry expected revisions where needed; conflicts preserve the operator's context and refresh current server state. Money and intervals include units and time conventions. The UI separates simulated behaviour, posted financial records and shadow-only results.

## Permissions and audit

Seed local viewer, operator and migration-approver identities. Viewer is read-only; operator can ingest and bill; approver can resolve discrepancies and change cohort routing. Enforce permissions on the server and record actor/time/reason for consequential actions. Choose the session mechanism, CSRF handling where applicable and GraphQL depth/cost bounds in TAR-009 before exposing mutations. No real customer PII or publicly accessible credentials are part of the demo.

## Client instances

Two fictional retailers run one application image with different policy configuration. They use separate core databases/roles, broker vhosts/credentials and configured service endpoints. The client identity is startup configuration, never trusted from a request field. Seed distinct accounts and overlapping external-looking identifiers to expose accidental cross-client lookups.

A local shared database server/broker is permitted but does not demonstrate independent fault domains. Client-specific packages cannot import each other. Core receives policies through composition and has no `if client == ...` branches.

## Acceptance

- Browser journeys cover import, bill explanation, correction, discrepancy review and cutover through the real API.
- Permission-negative cases fail at GraphQL/application boundaries and leave records unchanged.
- Reload after an ambiguous response locates the original operation.
- Stale comparison screens cannot approve a newer comparison implicitly.
- Both client instances use the same image digest; observed differences match their declared policies.
- Cross-client IDs, credentials and broker access cannot read or mutate the other client's state.
- Keyboard access, labelled controls and visible failure/loading/empty states are verified for the primary workflows.
