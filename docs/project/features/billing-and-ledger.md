# Billing, corrections and ledger

Date: 2026-10-25
Status: TAR-007/TAR-008 slices implemented and re-verified after independent-review remediation — commit-safe locked input revalidation, quarantine-aware digests, net-credit posting, transaction-scoped journal sealing, immutable rating snapshots. [Decision 003](../decisions/003-financial-and-migration-integrity.md) records the integrity model. The operator journey (TAR-009) is implemented; client isolation and remaining slices remain planning contracts.
Tasks: [TAR-007](../backlog.md#tar-007), [TAR-008](../backlog.md#tar-008), [TAR-009](../backlog.md#tar-009).

## Bill lifecycle

An authenticated operator requests billing for an account and period with an operation ID. Admission records intent durably and returns an operation identity. The run selects and records an immutable input generation, then calculates, validates and issues. Persist attempts separately from business outcomes. Failed, stale or incomplete runs cannot report an issued bill.

In one transaction, issuance checks expected input and routing versions, creates the numbered invoice, posts its balanced journal and completes the business operation. One account/period billing generation has at most one authoritative issuance even if different operation IDs race. Idempotent retry returns the existing outcome; changing the payload under an existing key is a conflict. Never call a remote service while holding a long-lived financial transaction open.

## Financial model

All posted monetary values are AUD; line precision and rounding are frozen by TAR-004. A journal comprises at least two postings with equal total debits and credits. Use an explicit minimal chart of accounts for customer receivables, energy revenue, export credits and any supported tax liability. This is a billing subledger, not a full general ledger or payments platform.

Posted invoices/journals are immutable through application and runtime database permissions. Corrections append linked documents; deletions or direct mutation of postings are not ordinary application operations. Define the cross-row balance enforcement and its concurrency tests in TAR-007. Every posting traces to a bill/adjustment, operation and source snapshot.

## Corrected data

An issued bill retains its original reading and tariff snapshot. A new effective revision schedules recalculation for affected periods. The adjustment equals the revised liability minus the net liability already recognised by the original bill and all posted adjustments. Never repeatedly subtract only the original total: successive revisions would double-adjust.

Serialize adjustment generations for each billing period and validate the current recognised generation at posting. A repeated correction is a no-op financially. A stale calculation cannot supersede a newer one. Zero-value corrections retain audit evidence without fabricating unnecessary money movement. Credit and debit adjustments are both supported.

## Failure acceptance

- Independent reference bills and journals reconcile to expected quantities and amounts.
- Duplicate requests, competing operation IDs and concurrent correction runs cannot duplicate issuance or adjustments.
- Terminate a real worker before commit and after commit/before acknowledgement: redelivery produces one financial effect.
- Broker unavailability after request commit retains durable pending work; relay recovery completes it.
- Publish/mark-delivered interruption and duplicate delivery are harmless.
- PostgreSQL failure produces no partial invoice/journal or false success.
- Current-input changes during rating require recalculation; stale runs remain inspectable.
- Negative tests prove forbidden posting mutation and unbalanced journals are rejected by the selected enforcement boundary.

Actual subprocess/container tests are required for crash claims; eager Celery tests alone are insufficient.
