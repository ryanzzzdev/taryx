# Metering and rating

Date: 2026-10-25
Status: Planning contract. Supported subset, time conventions and numeric profile frozen by TAR-004 on 2026-10-25 ([BLK-001](../blockers.md#blk-001) resolved). Reference cases live in [rating-reference-cases.md](rating-reference-cases.md).
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

## Frozen profile (TAR-004, 2026-10-25)

### Authoritative references

- [MDFF Specification NEM12 & NEM13, v2.7 (AEMO, 2025)](https://aemo.com.au/-/media/files/electricity/nem/retail_and_metering/market_settlement_and_transfer_solutions/2025/mdff-specification-nem12-nem13-v27.pdf) — record layout, blocking order, quality method 'V', reason-code rules, IntervalDate sequencing.
- [Metrology Procedure Part B (AEMO, v8.12 consultation draft)](https://www.aemo.com.au/-/media/files/stakeholder_consultation/consultations/nem-consultations/2025/october-2025-remp/final-stage/metrology-procedure-part-b-v812-clean.pdf) — quality flag meanings and replacement rules (also present in earlier released versions).
- [AEMO EMMS Data Model v5.4](https://tech-specs.docs.public.aemo.com.au/Content/TSP_EMMSDM54_Oct2024/EMMS_DMv5.4_Nov24.pdf) — "INTERVAL_DATETIME … fixed to the UTC+10 time zone (NEM time)"; interval-ending timestamps.
- [Project EDGE Data Specification Part A (AEMO)](https://www.aemo.com.au/-/media/files/initiatives/der/2023/project-edge---data-specification-part-a.pdf) — "NEM time … defined as AEST which is 10 hrs ahead of UTC".
- GST rate: 10% under the A New Tax System (Goods and Services Tax) Act 1999; GST-inclusive component = amount ÷ 11 (sourced).
- Channel letters cross-checked against AEMO example-file conventions as documented by retailers (Ergon, Shell Energy NEM12 guides): `E*` registers are energy delivered from the grid to the site; `B1` is site generation exported to the grid.

### Supported format subset

| Aspect | Frozen support |
| --- | --- |
| File | CSV MDFF, `VersionHeader=NEM12`, exactly one 100 and one 900 record, blocking order 100→200→300(→400)→900; record 500 (B2B) ignored if present but not required |
| Records parsed | 100 header, 200 NMI data details, 300 interval data, 400 interval event, 900 end |
| IntervalLength | 30 or 5 minutes only |
| Unit of measure | `kWh` only |
| Channels | `E*` registers (grid-delivered import) and `B1` (site generation export); other suffix letters rejected |
| QualityMethod | `A`, `S`, `E`, `F`; `V` on a 300 record requires 400 record(s) resolving per-interval quality |
| ReasonCode | Required on `S`/`F` intervals (per MDFF 3.3.5); retained as evidence, not interpreted |

Rejected with explicit errors: NEM13 files, zipped archives, multiple header blocks, non-kWh UOM, interval lengths other than 5/30, non-E/B suffixes, unknown NMI references, out-of-order 300 records.

### Time conventions

- All interval timestamps are **NEM time**: AEST, fixed UTC+10, no daylight saving (sourced). Stored internally as UTC instants; civil-time (e.g. Australia/Sydney) conversion happens only at presentation boundaries.
- Timestamps are **interval-ending**: interval *n* of IntervalDate *d* covers `(d 00:00 + (n-1)L, d 00:00 + nL]` NEM time. The value stamped 00:30 covers 00:00–00:30.
- Every NEM day therefore has exactly 48 (30-min) or 288 (5-min) intervals — including days that are 23/25 hours in civil time. DST transitions cannot produce partial NEM days; they only shift which UTC/civil instants the NEM day maps to.
- Billing periods are half-open `[start 00:00 NEM, end 00:00 NEM)` and carry the convention explicitly.
- The NEM *trading day* (04:00–04:00, settlement convention) is out of scope; retail billing aligns to NEM calendar days.

### Revision selection and conflicts

1. Quality precedence `A` > `F` > `S` > `E` selects the current value per interval (consistent with the metrology replacement rules: higher-ranked flags may replace lower-ranked ones).
2. Within equal quality, the record with the latest `MSATSLoadDateTime`, then `UpdateDateTime`, wins; batch/record identity breaks remaining ties deterministically.
3. Equal-precedence conflicting values are quarantined for operator review — never silently selected.
4. A new effective revision marks dependent calculations stale; issued bills are never rewritten.

### Numeric and tax profile

- Decimal arithmetic end-to-end. Interval quantities: full precision (no rounding on read). Money: `ROUND_HALF_UP` to 2 dp **per bill line**, then summed (fictional-retailer policy, frozen for testability).
- Rates are GST-exclusive. GST = 10% of GST-applicable lines, computed per line at 2 dp (sourced rate; applicability matrix below is fictional policy).
- GST applies to supply-charge and consumption lines. Export feed-in credits are treated as non-GST (fictional simplification; real FIT GST treatment varies by customer registration).
- Feed-in credit reduces the bill total; a net-negative bill is allowed and surfaces as a credit adjustment scenario.
- Tariff versions carry effective `[start, end)` dates in NEM time; a change inside a billing period splits calculation at the boundary. Missing/overlapping/ambiguous agreements are explicit errors.

### Exclusions (explicit)

NEM13/accumulated data, demand (kW/kVAr) registers, `Q`/`K`/`N` suffixes, NET-metered single-register files, AEMO substitution type 51–68 semantics, wholesale settlement, real customer data, and any claim of MSATS conformance.

## Measurement profile (TAR-004, closes BLK-003)

Reference environment (measured 2026-10-25): 14-core x86-64, 30 GiB RAM (~10 GiB free), NVMe SSD with 167 GiB free, Docker 29.7.2 / Compose v5.5.0, Linux 7.0. Idle stack baseline: ~1.2 GiB total across db/broker/api/worker/web; `/healthz` ≈ 18 ms; GraphQL ping ≈ 5.5 ms; taryx app image 391 MB.

| Rung | Workload | Status |
| --- | --- | --- |
| R1 (required) | 100 accounts × 30 NEM days × 48 intervals (30-min E1) + B1 on 25% of accounts ≈ 180k intervals | Frozen acceptance workload |
| R2 (optional) | 1 000 accounts × 30 NEM days × 288 intervals (5-min) ≈ 8.6 M intervals | Capacity experiment, clearly labelled |

Frozen budgets (initial, R1, on the reference environment):

- Ingest R1 end-to-end ≤ 90 s wall clock.
- Billing run ≤ 2 s per account p95; R1 batch ≤ 5 min total.
- API read p95 ≤ 500 ms during ingestion; no false completed operations under faults.
- Worker SIGKILL recovery ≤ 60 s with exactly one financial effect per operation.
- Stack memory ≤ 8 GiB during R1; no unbounded queue growth.

Budgets are provisional engineering gates, not production SLAs; changes require an explicit record.
