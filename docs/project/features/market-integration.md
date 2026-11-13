# Bounded market integration

Date: 2026-10-25
Status: Implemented and verified 2026-11-08 (TAR-015) — synthetic `taryx-market/1` per [decision 005](../decisions/005-market-workflow-contract.md): `market-sim` coordinator service, `taryx.core.market` adapter (durable workflow/inbox/exception/outbox), `/callbacks/transfers` ingress, `market.submit|sweep|drain` tasks, GraphQL admission + inspection, live E2E to `market_state: registered`. 19 tests including real-sim subprocess and four scenario delivery patterns.
Tasks: [TAR-014](../backlog.md#tar-014), [TAR-015](../backlog.md#tar-015).

M4 independent review (2026-11-08): implementation acceptance reopened for TAR-015, M4-F4–F8. [Findings and verification limits](../evidence/m4/m4-independent-review.md) supersede the M4 completion claims above; existing M3 approval is unchanged.

Round-2 independent review at `d1831219` (2026-11-08): M4-F5/F7/F8 remain open in TAR-015. [Evidence](../evidence/m4/m4-independent-review.md#round-2--independent-verification-2026-11-08). Remediation completion claims above are superseded; M3 approval is unchanged.

Round 3 at `4b65cf58` (2026-11-08): F5 resolved; core account services now own writes, but F7/F8 remain and F10 affects the submission budget. [Evidence](../evidence/m4/m4-independent-review.md#round-3--independent-verification-2026-11-08) supersedes earlier M4 completion claims. R3 remediation (2026-11-08): F7 boolean `last_seq` rejection, F8 `pending_transfer_id` per-correlation dedup in the accounts consumer, F10 POST-count attempt budget — all resolved; pending re-review. Round 4 (2026-11-08): F8 reproduced once more as a stale-instance race; remediated — correlation check is now atomic inside the conditional `UPDATE` (stale reads cannot register newer pending transfers); live image rebuilt to candidate. Pending re-review.

Round 4: F7/F10 reported cases verified; F8 remains open because correlation validation and mutation are not atomic against concurrent admission. [Review](../evidence/m4/m4-review-r4.md) supersedes the R3 claim that F8 is resolved.

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
