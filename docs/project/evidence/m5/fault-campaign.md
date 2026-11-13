# TAR-016 fault campaign — 2026-11-13 12:02 UTC

Method: real container faults only — `docker kill --signal=KILL` on the
worker at code-level fault points (`TARYX_BILLING_PRECOMMIT_SLEEP`,
`TARYX_BILLING_POSTCOMMIT_SLEEP`, `TARYX_MARKET_SUBMIT_SLEEP`),
`docker compose stop` for broker/market outages, and duplicate task
dispatches through the real broker. Invariants are verified by SQL
against the live database. Rerun: `uv run python
scripts/fault-campaign.py` (`FAULT_DAY0`/`FAULT_OP` shift op ids and
billing days). Machine-readable output: `fault-campaign.jsonl`.

## sigkill-before-commit — PASS: no invoice/journal leaked; drain produced exactly one balanced invoice
- Boundary: inside the issuing transaction, before COMMIT
- Invariant: no financial effect may leak; recovery yields exactly one
- Start: `{"op": "run2-s1-precommit"}`
- Observed: `{"mid": {"op_status": "pending", "invoices": 0, "unbalanced_journals": 0}, "after": {"invoices": 1, "unbalanced_journals": 0}}`

## sigkill-after-commit — PASS: committed invoice survived the kill; explicit redelivery added nothing
- Boundary: after the issuing transaction commits, before the task acks
- Invariant: exactly one invoice/journal; redelivery adds nothing
- Start: `{"op": "run2-s2-postcommit"}`
- Observed: `{"mid": {"op_status": "complete", "invoices": 1, "unbalanced_journals": 0}, "after": {"invoices": 1, "unbalanced_journals": 0}}`

## broker-outage-recovery — PASS: admission was durable with broker down; API stayed responsive; drain recovered
- Boundary: broker down at dispatch; admission is durable via the outbox
- Invariant: no lost intent; API responsive during outage; op completes after
- Start: `{"op": "run2-s3-broker", "pending_in_outbox": true, "api_ok": true, "gql_code": 403, "status": "pending"}`
- Observed: `{"status": "complete", "invoices": 1, "unbalanced_journals": 0}`

## duplicate-task-delivery — PASS: duplicate deliveries produced exactly one invoice
- Boundary: same operation delivered twice through the broker
- Invariant: at-least-once delivery yields exactly one financial effect
- Start: `{"op": "run2-s4-duplicate"}`
- Observed: `{"invoices": 1, "unbalanced_journals": 0}`

## abandoned-consumer-lease — PASS: queued intent survived the missing consumer; exactly once
- Boundary: task queued while no consumer exists
- Invariant: broker retains intent; the resumed worker processes it once
- Start: `{"op": "run2-s5-lease", "status": "pending"}`
- Observed: `{"status": "complete", "invoices": 1, "unbalanced_journals": 0}`

## market-adapter-restart — PASS: crash left a durable draft; the restarted worker's sweep polled-then-resubmitted to terminal
- Boundary: worker killed between durable attempt marker and counterparty POST
- Invariant: no invented outcome; durable draft reconciles via poll-first resend
- Start: `{"correlation_id": "7a6e9a9a-e94a-4dab-b57e-47134dec27c0"}`
- Observed: `{"mid_state": "draft:1", "final_state": "completed"}`

## billing-under-market-outage — PASS: billing issued while the market coordinator was down
- Boundary: market coordinator down during a billing run
- Invariant: billing availability is independent of market integration
- Start: `{"op": "run2-s7-outage"}`
- Observed: `{"status_while_market_down": "complete", "invoices": 1, "unbalanced_journals": 0}`
