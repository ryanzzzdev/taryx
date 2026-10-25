# 003 — Durable financial operations and side-effect-free comparison

Date: 2026-10-25
Status: Accepted
Acceptance source: Financial auditability, correction history and safe shadow migration are part of the agreed concept. Outbox, immutable snapshot and single-writer details are design selections within delegated planning authority, not separately user-reviewed implementations.

## Context

Workers can fail after committing, brokers can be unavailable, meter data changes, and two callers can request the same bill with different request IDs. A matching invoice total alone cannot establish migration safety.

## Decision

Use PostgreSQL operation/outbox records with at-least-once delivery and idempotent consumers. Pin calculation inputs and enforce unique business issuance identities. Post invoices and balanced journals atomically; corrections append adjustments relative to all recognised liability. Validate generation/version preconditions at issuance.

Legacy and replacement calculators return results; core alone issues financial records. Shadow execution has restricted financial write access and compares item-level evidence. Decisions approving legacy differences are version-scoped. Cutover checks evidence freshness and in-flight operations. Rollback changes future routing, not posted accounting history.

## Alternatives

Broker-only state can lose admitted intent; post-commit callbacks alone leave a publication gap. Comparing totals misses offsetting defects. Letting both engines post bills risks duplicate effects. Rewriting issued invoices loses historical truth. Recomputing every correction against only the original bill duplicates earlier adjustments.

## Consequences and follow-up

Outbox relay/reconciliation and explicit generations add complexity in exchange for testable invariants. TAR-007 must choose and verify cross-row journal-balance enforcement; TAR-011 freezes evidence coverage/freshness rules. Process-fault and concurrency evidence is required before claiming guarantees. See [billing](../features/billing-and-ledger.md) and [migration](../features/legacy-migration.md).
