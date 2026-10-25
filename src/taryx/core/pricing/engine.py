"""Deterministic itemised rating — pure arithmetic, separately testable.

Inputs are immutable snapshots (interval quantities, agreement spans,
tariff specs). Money rounds ROUND_HALF_UP to 2 dp per line, then sums;
GST applies per line to supply and import elements only (fictional
retailer policy, per the frozen profile).
"""

from dataclasses import dataclass
from datetime import date, time
from decimal import ROUND_HALF_UP, Decimal

from taryx.core.pricing.tariffs import TariffSpec

ENGINE_VERSION = "1"
MONEY = Decimal("0.01")
GSTABLE_ELEMENTS = {"supply", "import"}
_ELEMENT_ORDER = {"import": 0, "export_credit": 1, "supply": 2}


class RatingError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


@dataclass(frozen=True)
class AgreementSpan:
    agreement_id: int
    tariff_code: str
    version: int
    effective_from: date
    effective_to: date | None

    def covers(self, day: date) -> bool:
        return self.effective_from <= day and (self.effective_to is None or day < self.effective_to)


@dataclass(frozen=True)
class IntervalQty:
    day: date
    end_tod: time
    value: Decimal


@dataclass(frozen=True)
class ChannelSlice:
    channel_id: int
    suffix: str
    direction: str
    intervals: tuple[IntervalQty, ...]


@dataclass(frozen=True)
class ComputedLine:
    agreement_id: int
    tariff_code: str
    segment_from: date
    segment_to: date
    element: str
    band: str | None
    quantity: Decimal
    unit: str
    rate: Decimal
    amount: Decimal
    gst: Decimal
    basis: str


@dataclass(frozen=True)
class RatingCalc:
    lines: tuple[ComputedLine, ...]
    net: Decimal
    gst: Decimal
    total: Decimal


def _round(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _segments(
    days: list[date], agreements: list[AgreementSpan]
) -> list[tuple[AgreementSpan, date, date]]:
    """Map each day to its single covering agreement; merge consecutive days."""
    spans: list[tuple[AgreementSpan, date, date]] = []
    for day in days:
        covering = [a for a in agreements if a.covers(day)]
        if not covering:
            raise RatingError("missing_agreement", f"no tariff agreement covers {day}")
        if len(covering) > 1:
            raise RatingError(
                "overlapping_agreements",
                f"{len(covering)} tariff agreements cover {day}",
            )
        agreement = covering[0]
        if spans and spans[-1][0].agreement_id == agreement.agreement_id:
            spans[-1] = (agreement, spans[-1][1], day)
        else:
            spans.append((agreement, day, day))
    return spans


def _band_for(end_tod: time, spec: TariffSpec):
    catch_all = None
    for band in spec.import_bands:
        if band.window is None:
            catch_all = band
        elif band.covers(end_tod):
            return band
    if catch_all is not None:
        return catch_all
    raise RatingError(
        "uncovered_band", f"no import band covers interval ending {end_tod} on {spec.code}"
    )


def rate(
    *,
    days: list[date],
    agreements: list[AgreementSpan],
    tariffs: dict[str, TariffSpec],
    channels: list[ChannelSlice],
    gst_rate: Decimal,
) -> RatingCalc:
    """Rate the pinned inputs into itemised GST-inclusive lines."""

    def line(
        agreement: AgreementSpan,
        spec: TariffSpec,
        seg: tuple[date, date],
        element: str,
        band: str | None,
        quantity: Decimal,
        unit: str,
        rate_: Decimal,
        basis: str,
    ) -> ComputedLine:
        sign = Decimal(-1) if element == "export_credit" else Decimal(1)
        amount = _round(sign * quantity * rate_)
        gst = _round(amount * gst_rate) if element in GSTABLE_ELEMENTS else Decimal(0)
        return ComputedLine(
            agreement_id=agreement.agreement_id,
            tariff_code=spec.code,
            segment_from=seg[0],
            segment_to=seg[1],
            element=element,
            band=band,
            quantity=quantity,
            unit=unit,
            rate=rate_,
            amount=amount,
            gst=gst,
            basis=basis,
        )

    lines: list[ComputedLine] = []
    for agreement, seg_from, seg_to in _segments(days, agreements):
        spec = tariffs.get(agreement.tariff_code)
        if spec is None:
            raise RatingError(
                "unknown_tariff", f"no tariff spec for code {agreement.tariff_code!r}"
            )
        seg_days = {d for d in days if seg_from <= d <= seg_to}
        seg = (seg_from, seg_to)

        for channel in channels:
            items = [i for i in channel.intervals if i.day in seg_days]
            if channel.direction == "import":
                for band in spec.import_bands:
                    band_items = [i for i in items if _band_for(i.end_tod, spec) is band]
                    if not band_items:
                        continue
                    qty = sum((i.value for i in band_items), Decimal(0))
                    lines.append(
                        line(
                            agreement,
                            spec,
                            seg,
                            "import",
                            band.name,
                            qty,
                            "kWh",
                            band.price,
                            f"sum of {len(band_items)} interval values on "
                            f"{channel.suffix} over {len(seg_days)} days",
                        )
                    )
            elif channel.direction == "export" and spec.export_credit_per_kwh is not None:
                qty = sum((i.value for i in items), Decimal(0))
                if qty:
                    lines.append(
                        line(
                            agreement,
                            spec,
                            seg,
                            "export_credit",
                            None,
                            qty,
                            "kWh",
                            spec.export_credit_per_kwh,
                            f"feed-in credit on {len(items)} interval values "
                            f"on {channel.suffix} over {len(seg_days)} days",
                        )
                    )

        lines.append(
            line(
                agreement,
                spec,
                seg,
                "supply",
                None,
                Decimal(len(seg_days)),
                "day",
                spec.supply_per_day,
                f"daily supply charge over {len(seg_days)} days",
            )
        )

    lines.sort(
        key=lambda item: (
            item.segment_from,
            _ELEMENT_ORDER[item.element],
            item.band or "",
            item.tariff_code,
        )
    )
    net = sum((line.amount for line in lines), Decimal(0))
    gst = sum((line.gst for line in lines), Decimal(0))
    return RatingCalc(tuple(lines), net, gst, net + gst)
