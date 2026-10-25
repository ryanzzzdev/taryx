"""Field-level comparison of new-engine and legacy calculation lines.

Pure and deterministic. Lines pair by identity
(element, band, segment, tariff_code); quantity, rate, amount and gst
are compared per pair, then totals. Any field difference — including
differences that cancel in the totals — yields DIFFERENCE, never MATCH.
"""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from taryx.core.migration.legacy_adapter import LegacyResult
from taryx.core.pricing.models import RatingRun


@dataclass(frozen=True)
class LineDiff:
    """One field-level difference; fingerprint scopes approvals."""

    account: str
    element: str
    band: str | None
    segment_from: str
    segment_to: str
    field: str
    new_value: str
    legacy_value: str
    detail: str

    @property
    def fingerprint(self) -> str:
        canonical = "|".join(
            [
                self.account,
                self.element,
                self.band or "",
                self.segment_from,
                self.segment_to,
                self.field,
                self.new_value,
                self.legacy_value,
            ]
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def as_dict(self) -> dict:
        return {
            "fingerprint": self.fingerprint,
            "element": self.element,
            "band": self.band,
            "segment": [self.segment_from, self.segment_to],
            "field": self.field,
            "new": self.new_value,
            "legacy": self.legacy_value,
            "detail": self.detail,
        }


_FIELDS = ("quantity", "rate", "amount", "gst")


def _identity(element: str, band, seg_from, seg_to, tariff_code) -> tuple:
    return (element, band or "", str(seg_from), str(seg_to), tariff_code)


def diff_lines(run: RatingRun, result: LegacyResult, account_ref: str) -> list[LineDiff]:
    """Pair new-engine lines to legacy lines; return field-level diffs."""
    new_lines = run.lines.all()
    legacy_by_id = {
        _identity(
            line.element, line.band, line.segment_from, line.segment_to, line.tariff_code
        ): line
        for line in result.lines
    }
    new_by_id = {
        _identity(
            line.element, line.band, line.segment_from, line.segment_to, line.tariff_code
        ): line
        for line in new_lines
    }
    diffs: list[LineDiff] = []
    for key in sorted(set(legacy_by_id) | set(new_by_id)):
        element, band, seg_from, seg_to, _ = key
        base = dict(
            account=account_ref,
            element=element,
            band=band or None,
            segment_from=seg_from,
            segment_to=seg_to,
        )
        new_line = new_by_id.get(key)
        legacy_line = legacy_by_id.get(key)
        if new_line is None:
            diffs.append(
                LineDiff(
                    **base,
                    field="line",
                    new_value="absent",
                    legacy_value="present",
                    detail="legacy produced a line the new engine did not",
                )
            )
            continue
        if legacy_line is None:
            diffs.append(
                LineDiff(
                    **base,
                    field="line",
                    new_value="present",
                    legacy_value="absent",
                    detail="new engine produced a line legacy did not",
                )
            )
            continue
        pairs = {
            "quantity": (new_line.quantity, legacy_line.quantity),
            "rate": (new_line.rate, legacy_line.rate),
            "amount": (new_line.amount, legacy_line.amount),
            "gst": (new_line.gst, legacy_line.gst),
        }
        for field, (new_val, legacy_val) in pairs.items():
            if Decimal(new_val) != Decimal(legacy_val):
                diffs.append(
                    LineDiff(
                        **base,
                        field=field,
                        new_value=str(new_val),
                        legacy_value=str(legacy_val),
                        detail=f"{field} differs: new {new_val} vs legacy {legacy_val}",
                    )
                )
    for field, (new_val, legacy_val) in {
        "net": (run.net, result.net),
        "gst_total": (run.gst, result.gst),
        "total": (run.total, result.total),
    }.items():
        if new_val != legacy_val:
            diffs.append(
                LineDiff(
                    account=account_ref,
                    element="__totals__",
                    band=None,
                    segment_from=str(run.period_start),
                    segment_to=str(run.period_end),
                    field=field,
                    new_value=str(new_val),
                    legacy_value=str(legacy_val),
                    detail=f"bill {field} differs: new {new_val} vs legacy {legacy_val}",
                )
            )
    return diffs


def report(run: RatingRun, result: LegacyResult, account_ref: str) -> dict:
    diffs = diff_lines(run, result, account_ref)
    return {
        "status": "difference" if diffs else "match",
        "new_engine_version": run.engine_version,
        "legacy_engine_version": result.engine_version,
        "legacy_catalogue_version": result.catalogue_version,
        "policy_identity": run.policy_identity,
        "snapshot_hash": run.input_digest,
        "totals": {
            "new": {"net": str(run.net), "gst": str(run.gst), "total": str(run.total)},
            "legacy": {
                "net": str(result.net),
                "gst": str(result.gst),
                "total": str(result.total),
            },
        },
        "diffs": [d.as_dict() for d in diffs],
    }


def report_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
