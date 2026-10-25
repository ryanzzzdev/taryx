# Metering and rating

Date: 2026-10-25
Status: Planning contract; exact supported NEM12 subset and numeric/time profile are gated by [BLK-001](../blockers.md#blk-001).
Tasks: [TAR-004](../backlog.md#tar-004), [TAR-005](../backlog.md#tar-005), [TAR-006](../backlog.md#tar-006).

## User outcome

An operator imports synthetic interval data, sees accepted/rejected records and provenance, and can explain the quantities and rates behind each bill line. Supported tariffs begin with daily supply, time-of-use import and solar export credits. Demand charges, wholesale pass-through and VPP incentives are excluded initially.

## Inputs and history

Record supply point, meter/channel, direction, interval boundaries, unit, quality, source batch/hash and source revision information. Preserve raw source evidence and revisions; do not overwrite previous readings. A stable interval identity and explicit source precedence determine the current selection, not arrival order. Duplicate batches and repeated revisions are no-ops with inspectable results. Equal-precedence conflicting values are quarantined for review, not silently selected.

Validate file size, supported records, interval lengths, units, ordering and supply-point references. Stage a batch before publishing its accepted revision set; parsing failure must not leave a partially current billing dataset. If chunked ingestion is chosen, freeze its atomic visibility contract before implementation. Invalid or incomplete coverage blocks issuance by default; no silent zero filling or invented estimates.

## Frozen calculation inputs

The billing period uses half-open boundaries and carries its time convention explicitly. NEM meter timestamps, tariff civil time and UTC storage must be distinguished. TAR-004 must resolve interval-end conventions, daylight-saving transitions, leap days and effective-date changes against authoritative format documentation. Do not assume every day has 288 civil-time intervals or every NEM12 record is five-minute data.

Record selected reading revisions, tariff version, agreement effective dates, client policy identity and calculation engine version in an immutable snapshot. Use Decimal for quantities and rates, with explicit units and rounding points. Tariff changes inside a period split calculations according to effective dates. Missing, overlapping or ambiguous agreements produce explicit errors.

## Evidence and acceptance

- Hand-worked reference cases independently verify flat/time-of-use charges, export credits, daily charges and chosen tax/rounding rules.
- A tariff boundary, leap day and applicable daylight-saving boundary have explicit expected quantities and amounts.
- Duplicate, out-of-order, conflicting and corrected readings preserve provenance and deterministic selection.
- Malformed input, unsupported interval/unit, incomplete coverage and unknown meters fail visibly.
- Re-running the same snapshot produces the same itemised result and digest.
- Seed fixtures carry deterministic generator parameters, intended defects and independent expected results; expected results must not be computed by the engine under test.

Australian regulatory/tax claims require linked authoritative sources in the frozen profile. Fictional retailer policies are labelled as such. Implementation is blocked on the relevant profile decisions, not on the entire project.
