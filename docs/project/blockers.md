# Taryx blockers and open questions

Date: 2026-10-25

No obstacle prevents documentation or initial bootstrap. The following bounded design gates prevent unsupported implementation choices, not all project progress. IDs are never reused.

<a id="blk-001"></a>

## BLK-001 — Supported metering and tariff profile

- Identified: 2026-10-25
- Status: Open
- Affects: TAR-004–008; M1/M2.
- Impact: Meter revision selection, time conversion, tax/rounding and reference amounts cannot be implemented credibly from earlier chat examples alone.
- Evidence: The concept specifies NEM12 and Australian tariffs without a frozen schema/version, quality precedence or time profile. Earlier illustrative regulatory claims were explicitly rejected.
- Blocks now: Production-like ingestion/rating implementation; does not block workspace bootstrap or source research.
- Next action/owner: Implementing agent on TAR-004 selects authoritative AEMO format documentation and relevant sources for any claimed rules, declares a bounded supported subset, documents fictional policies and produces independent reference cases. Unsupported scenarios are rejected explicitly.
- Resolution: Pending. Record date, profile and evidence before closing.

<a id="blk-002"></a>

## BLK-002 — Exact market interaction and protocol

- Identified: 2026-10-25
- Status: Open
- Affects: TAR-014–015; M4.
- Impact: Adapter transitions, reconciliation and simulator behaviour need one consistent contract.
- Evidence: The reviewed concept proposes a bounded transfer/role interaction but does not establish an actual AEMO procedure or supported protocol.
- Blocks now: Market implementation only; core billing and migration can proceed.
- Next action/owner: Implementing agent on TAR-014 documents the scenario, state table, protocol version, correlation, authentication and recovery rules. Use a clearly synthetic protocol unless primary-source research supports a named standard subset. Escalate only a material scope change to the user.
- Resolution: Pending.

<a id="blk-003"></a>

## BLK-003 — Reference workload and resource budgets

- Identified: 2026-10-25
- Status: Open
- Affects: TAR-004, TAR-016–018; M1/M5.
- Impact: No defensible throughput, latency, recovery or resource acceptance threshold exists yet.
- Evidence: Portfolio scale and 6–10 week ambition do not define a measurement environment. Large interval fixtures can exceed laptop memory/storage budgets.
- Blocks now: Performance acceptance claims; does not block functional bootstrap.
- Next action/owner: Implementing agent records available CPU/memory/storage and baseline behaviour after TAR-003, selects a required local workload with bounded fixtures and freezes budgets in TAR-004 before optimisation. Keep larger stress rungs optional and labelled.
- Resolution: Pending.
