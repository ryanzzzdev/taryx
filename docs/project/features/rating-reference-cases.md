# Independent rating and ingestion reference cases

Date: 2026-10-25
Status: Frozen by TAR-004. Expected values are computed by hand from the [frozen profile](metering-and-rating.md#frozen-profile-tar-004-2026-10-25) — never derived from the engine under test.
Tasks: [TAR-005](../backlog.md#tar-005), [TAR-006](../backlog.md#tar-006), [TAR-008](../backlog.md#tar-008).

## Shared fixture frame

Fictional retailer rates, GST-exclusive (labelled fictional policy, not an Australian offer):

| Tariff | Element | Rate |
| --- | --- | --- |
| T-FLAT | Daily supply | $1.1000/day |
| T-FLAT | Import energy | $0.3000/kWh flat |
| T-TOU | Daily supply | $1.1000/day |
| T-TOU | Peak import | $0.4000/kWh — interval endings in (07:00, 22:00] NEM |
| T-TOU | Off-peak import | $0.2000/kWh otherwise |
| FIT | Export credit | $0.0500/kWh on B1 |

GST 10% applies to supply and import lines only (per frozen profile). Money rounds `ROUND_HALF_UP` to 2 dp per line.

## RC-01 — Flat rate, one NEM day

Input: E1 = 0.5 kWh every 30-min interval, 2026-03-02 (48 intervals, `A` quality).

| Line | Computation | Amount |
| --- | --- | --- |
| Import energy | 48 × 0.5 = 24.0 kWh × $0.30 | $7.20 |
| Daily supply | 1 day × $1.10 | $1.10 |
| Net | | $8.30 |
| GST | 0.72 + 0.11 | $0.83 |
| **Total** | | **$9.13** |

## RC-02 — TOU split, one NEM day

Same 24 kWh uniform profile on T-TOU.

| Line | Computation | Amount |
| --- | --- | --- |
| Peak import | 30 intervals (endings 07:30–22:00) = 15.0 kWh × $0.40 | $6.00 |
| Off-peak import | 18 intervals = 9.0 kWh × $0.20 | $1.80 |
| Daily supply | | $1.10 |
| Net | | $8.90 |
| GST | 0.60 + 0.18 + 0.11 | $0.89 |
| **Total** | | **$9.79** |

Peak boundary check: the interval ending 07:00 is off-peak (covers 06:30–07:00); the interval ending 22:00 is peak.

## RC-03 — Export credit on the same day

Add B1 = 0.2 kWh every interval to RC-01 (flat tariff + FIT).

| Line | Computation | Amount |
| --- | --- | --- |
| Import + supply net | as RC-01 | $8.30 |
| Export credit | 48 × 0.2 = 9.6 kWh × $0.05 | −$0.48 |
| Net | | $7.82 |
| GST | charge lines only, as RC-01 | $0.83 |
| **Total** | | **$8.65** |

## RC-04 — Tariff effective-date boundary mid-period

T-FLAT v1 $0.30/kWh effective [2026-01-01, 2026-01-15) NEM; v2 $0.35/kWh from 2026-01-15. Billing period [2026-01-01, 2026-02-01), uniform 24 kWh/day.

| Segment | Computation | Amount |
| --- | --- | --- |
| Import v1 | 14 days × 24 kWh × $0.30 | $100.80 |
| Import v2 | 17 days × 24 kWh × $0.35 | $142.80 |
| Supply | 31 × $1.10 | $34.10 |
| Net | | $277.70 |
| GST | 10.08 + 14.28 + 3.41 | $27.77 |
| **Total** | | **$305.47** |

## RC-05 — Leap day and February 2028

NEM day 2028-02-29 has 48 intervals (leap days are ordinary days in NEM time). Uniform profile on T-FLAT gives the RC-01 daily figures.

Period [2028-02-01, 2028-03-01) contains exactly 29 NEM days → 29 × $9.13 total = **$264.77** (net $240.70, GST $24.07).

## RC-06 — DST transition days (statement-level)

- 2026-10-04 (AEDT begins) and 2027-04-04 (AEDT ends) each contain exactly 48 × 30-min intervals in NEM time.
- The NEM day 2026-10-04 maps to UTC [2026-10-03T14:00Z, 2026-10-04T14:00Z); the Sydney civil date has 23 hours, but the interval count is unchanged.
- Expected: fixtures for these dates produce full coverage; no code path may assume 288/48 intervals per civil day.

## RC-07 — Revision selection

| Case | Records | Expected |
| --- | --- | --- |
| (a) E then A | interval ending 10:00: `E` 0.4 kWh, later `A` 0.5 kWh | selected `A` 0.5 kWh; `E` retained in history |
| (b) S then F | `S` 0.6 kWh, later `F` 0.55 kWh | selected `F` 0.55 kWh |
| (c) equal-precedence conflict | two `A` records, same interval/timestamps, values 0.4 vs 0.6 kWh | interval quarantined; coverage incomplete; no silent choice |

## RC-08 — Rejected inputs (each an independently expected failure)

| Input defect | Expected outcome |
| --- | --- |
| `UOM=MWH` | batch rejected, reason recorded |
| `IntervalLength=15` | batch rejected |
| `VersionHeader=NEM13` | batch rejected |
| 300 record for unknown NMI | batch rejected |
| 300 records out of date order | batch rejected |
| Billing over a period with missing intervals | issuance blocked; no silent zero-fill |

## RC-09 — Successive correction (adjustment contract)

Bill issued for RC-01 ($9.13). Interval ending 10:00 is revised `A` 0.5 → 0.8 kWh (day import becomes 24.3 kWh).

- Revised liability: 24.3 × 0.30 = 7.29 + 1.10 = 8.39 net, GST 0.73 + 0.11 = 0.84 → $9.23.
- Adjustment = revised − net recognised = 9.23 − 9.13 = **+$0.10 debit**.
- A second revision to 0.6 kWh (24.1 kWh): revised total = 7.23 + 1.10 = 8.33 net, GST 0.83 → $9.16. Adjustment = 9.16 − 9.23 = **−$0.07 credit** (vs. recognised, not vs. original).
- Re-submitting identical revision: **$0.00 adjustment**, audit record only.
