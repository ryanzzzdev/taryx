# Operator portal and client isolation

Date: 2026-10-25
Status: TAR-009 slice implemented and re-verified after independent-review remediation (decision 004 contract: session auth, roles, bounded GraphQL, operation polling, audit, portal journey, CSRF origin bootstrap, durable browser operation IDs). Client isolation implemented and verified 2026-11-08 (TAR-013): one image, two retailer deployments — separate database/role (`taryx_app`/`taryx` vs `taryx_sg`/`taryx_southgrid`), broker vhost/user (`taryx` vs `taryx-sg`, creator auto-grant revoked), per-client legacy simulator volume and web port; client identity via `TARYX_CLIENT` startup config resolved once in `taryx.composition.policy`; refused cross-client CONNECT/AMQP verified live; southgrid rated the same day/account at 9.59 vs aurora 8.75. Limits: shared Postgres server and broker — credentials/data/route isolation, not independent fault domains.
Re-review at `de0e08d`: rating snapshot/membership and browser account-recovery claims above are only partially verified; see [remaining findings](../evidence/m2/m2-independent-review.md). M2 remains open.
Tasks: [TAR-009](../backlog.md#tar-009), [TAR-012](../backlog.md#tar-012), [TAR-013](../backlog.md#tar-013).

2026-11-08: TAR-009 reopened by [foundation re-review F3](../evidence/m1/m1-independent-review.md): invoice totals and ledger legs are visible, but the required pinned line-item explanation is absent; round 2 confirmed new-engine lines but not authoritative legacy evidence. Remediated same day — issued documents expand into the pinned *authoritative* calculation's line items (tariff, segment, quantity, rate, amount, basis; `calculationSource` distinguishes the engine), reconciling to the invoice total for both engines.

Round-three review at `e809640` found persisted-line rendering and mutable pinned evidence gaps (F3/F4); remediated same day — real legacy lines render and the pinned LegacyCalculation is immutable at the database level. [Review](../evidence/m1/m1-independent-review.md).

Latest independent verification (2026-11-08, `2704f119`): F3/F4 resolved and foundation review approved. Persisted authoritative legacy lines render and reconcile; database triggers reject UPDATE and DELETE of that evidence. New-engine pinning and API journey regressions pass. Verification combines source/API/frontend checks and the real legacy simulator; no fresh interactive browser session is claimed. Earlier open findings above are historical.

M4 independent review (2026-11-08): implementation acceptance reopened for TAR-013, M4-F1–F3. [Findings and verification limits](../evidence/m4/m4-independent-review.md) supersede the M4 completion claims above; existing M3 approval is unchanged.

Round-2 independent review at `d1831219` (2026-11-08): TAR-013 reopened for M4-F9: both runtime shadow credentials can read the other client database. [Evidence](../evidence/m4/m4-independent-review.md#round-2--independent-verification-2026-11-08). Remediation completion claims above are superseded; M3 approval is unchanged.

Round 3 at `4b65cf58` (2026-11-08): F9 cross-client shadow isolation verified resolved; F11 shows different running application image IDs, leaving TAR-013 incomplete. [Evidence](../evidence/m4/m4-independent-review.md#round-3--independent-verification-2026-11-08) supersedes earlier M4 completion claims. R3 remediation (2026-11-08): all four app services now deploy one named `taryx-app:latest` image — one shared digest verified live; `taryx_app` owns its objects for migrations. Pending re-review.

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
