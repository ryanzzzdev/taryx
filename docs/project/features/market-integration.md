# Bounded market integration

Date: 2026-10-25
Status: Extension design; exact workflow and schema are Proposed pending [BLK-002](../blockers.md#blk-002).
Tasks: [TAR-014](../backlog.md#tar-014), [TAR-015](../backlog.md#tar-015).

## Boundary

Demonstrate one asynchronous supply-point interaction, such as a simplified transfer request. The adapter owns durable workflow state, outbound requests, correlation and reconciliation. The external simulator owns the counterparty response schedule. Neither may directly update core billing/account tables. The adapter sends versioned outcomes that the core validates and deduplicates.

A synthetic JSON/HTTP protocol is acceptable only when clearly labelled as a Taryx simulation. Calling it an AEMO-compatible implementation requires a sourced protocol subset and conformance checks. Do not invent cooling-off/objection sequences or present simulated timing as market procedure.

## Required behaviour

Freeze a transition table with allowed, rejected, duplicate, late and out-of-order events before coding. Maintain a received-message inbox and transactional workflow/outbox updates. Retry transport failures with bounded backoff; business rejections are terminal or require an explicit new operation, not endless retries. Unknown correlation IDs and impossible transitions enter an inspectable exception state.

Persist deadlines, attempts and last-known counterparty status. Reconcile uncertain outcomes rather than resubmitting a logically new request after a timeout. A delayed completion cannot overwrite a newer terminal decision without an explicitly permitted transition. Simulator scenarios are deterministic from a seed/script and independently replayable.

## Acceptance

- A normal request completes and its outcome is reflected in core through the published contract.
- Duplicate submissions and callbacks produce one business transition.
- Out-of-order, delayed, rejected and malformed responses follow the frozen state table.
- Lost responses and adapter restarts recover using durable state and reconciliation.
- Counterparty unavailability does not block core API responsiveness or unrelated billing.
- Version, client identity and correlation mismatches fail visibly without state corruption.

Full MSATS, aseXML coverage, AEMO credentials and live market connectivity are excluded.
