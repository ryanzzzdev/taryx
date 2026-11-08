# Legacy comparison and cohort migration

Latest verification (2026-11-08 UTC): **approved** at `64ace7dda5a44ddede4a91f74d54eb85e03bfbe8`.
TAR-010–012 are verified complete within the [review limits](../evidence/m3-re-review.md#round-two-resumed-independent-verification).
Missing import usage or daily supply fails response validation. Malformed
legacy billing responses terminate the operation as FAILED without issuance;
SHADOW failures persist INCONCLUSIVE gate evidence before propagating. Timeout
and unavailable remain PENDING/retryable. Export-credit differences remain
comparison evidence. Earlier verification statements below are historical.

Latest verification (2026-11-08): **changes requested** at `7d6c633`;
M3-RR-F1/F2 remediated the same day — strict per-field line validation and
import-usage completeness reconciliation route malformed responses through
INCONCLUSIVE evidence and a terminal FAILED operation rather than issuing
partial invoices or retrying forever. [Fresh independent review](../evidence/m3-re-review.md).
Earlier verification statements below are historical.

Current independent verification at `db18588`: one cutover evidence-update race remains (F2); see [review](../evidence/m3-independent-review.md). Other prior finding probes pass.
Date: 2026-10-25
Status: implemented but reopened by [independent M3 review](../evidence/m3-independent-review.md); TAR-010/011/012 are not verified complete. Independent `legacy-sim` service (own sqlite schema, protocol `taryx-legacy/1`, catalogue `L-2003.4`) with characterised heritage GST-exempt policy and FIT-TRUNC-2003 defect (TAR-010); comparison evidence, scoped decisions and frozen cutover gates (TAR-011); routing-pinned billing, GraphQL controls, portal journey and audited transitions (TAR-012). Fictional policies and legacy defects are test scenarios, not Australian regulations.
Current verification at `f9f21df`: latest-failure gating, complete approval revalidation, rollback corrections and malformed-value handling remain unresolved; see [review](../evidence/m3-independent-review.md).
Tasks: [TAR-010](../backlog.md#tar-010), [TAR-011](../backlog.md#tar-011), [TAR-012](../backlog.md#tar-012).

## Scope and authority

The independently deployed legacy calculator owns a separate legacy schema and exposes versioned calculation responses. It does not post Taryx invoices. Both engines consume an equivalent immutable snapshot; the core is the only authoritative financial writer. Document the adapter mapping explicitly so comparing engines does not also compare different data.

Cohort modes: `LEGACY_ONLY` uses the legacy result; `SHADOW` still uses the legacy result and compares the new result without side effects; `NEW_ONLY` uses the new result. Routing changes affect future admitted work. Pin mode and routing revision on each operation; block or drain in-flight issuance before a cohort changes modes.

## Characterisation and comparison

A documented grandfathered client policy and a deliberately seeded legacy arithmetic defect provide distinct scenarios. Characterisation tests preserve observed behaviour without automatically declaring it correct. Tests must expose the two defects independently and must not merely call the same shared calculation from both engines.

Compare component identities, quantities, rates, tariff/policy versions, rounding and final amounts. Reports retain both engine versions, snapshot hash, cohort revision, timestamps and field-level differences. A timeout, missing result or malformed legacy response is inconclusive and blocks migration evidence; it is not a successful comparison.

Classify discrepancies as unresolved, preserve-client-policy or approved-legacy-defect-correction. Record actor, reason, evidence and affected versions. Approval of a defect is scoped to that specific difference and version, not a blanket tolerance for later mismatches. Changed inputs, policies or engines invalidate stale approvals/evidence for cutover.

## Cutover control

An authorised approver can cut over only when the declared cohort evaluation set is complete, no required comparison is inconclusive or unresolved, approved differences are still applicable and routing/version preconditions match. The evaluation set and freshness rules are frozen in TAR-011 (implemented in `evaluation_blockers`) and visible to the operator; passing sample accounts cannot imply all accounts were compared. Frozen rules: every member account needs comparison evidence for the declared period that postdates `eval_frozen_at`, is conclusive, pins the current input digest and current engine/policy versions, and has a still-valid scoped `DiscrepancyDecision` per difference fingerprint. Gate-affecting writes (comparison evidence, scoped decisions, memberships) serialize with the cutover through a cohort-scoped advisory lock held from the final gate re-read until the route commit — no evidence commit can land inside that window.

Changes are audited and use optimistic concurrency to reject stale requests. Routing rollback stops future use of the new calculator; it cannot undo financial documents. Existing bills require the normal adjustment path. Do not advertise arbitrary state rollback or migration of historical debt/account data.

## Acceptance

- Shadow credentials and code paths cannot issue invoices or modify ledger tables; test attempted writes, not just UI visibility.
- Two offsetting line differences are detected even when final totals match.
- The historical client policy is preserved and the known legacy bug is explicitly corrected with scoped evidence.
- Legacy timeout and malformed output block cutover; restart/retry preserves comparison identity.
- Concurrent cutover, stale evidence and in-flight billing cannot produce mixed authoritative generation decisions.
- A cohort can move from legacy to shadow to new, while another remains legacy, with an auditable history.
