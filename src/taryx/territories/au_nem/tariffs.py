"""Fictional retailer tariff catalogue for the au_nem territory.

Fictional policy labelled as such (per the frozen profile): rates are
GST-exclusive, GST 10% applies to supply and import lines, and the peak
window is interval endings in (07:00, 22:00] NEM time.
"""

from datetime import time
from decimal import Decimal

from taryx.core.pricing.tariffs import RateBand, TariffSpec

CATALOGUE_VERSION = "2026-10-25"
POLICY_IDENTITY = f"au_nem-retail-catalogue/{CATALOGUE_VERSION}"
GST_RATE = Decimal("0.10")

_PEAK_WINDOW = (time(7, 0), time(22, 0))

TARIFFS: dict[str, TariffSpec] = {
    "T-FLAT": TariffSpec(
        code="T-FLAT",
        version=CATALOGUE_VERSION,
        supply_per_day=Decimal("1.10"),
        import_bands=(RateBand("flat", Decimal("0.30")),),
    ),
    "T-FLAT-V2": TariffSpec(
        code="T-FLAT-V2",
        version=CATALOGUE_VERSION,
        supply_per_day=Decimal("1.10"),
        import_bands=(RateBand("flat", Decimal("0.35")),),
    ),
    "T-TOU": TariffSpec(
        code="T-TOU",
        version=CATALOGUE_VERSION,
        supply_per_day=Decimal("1.10"),
        import_bands=(
            RateBand("peak", Decimal("0.40"), _PEAK_WINDOW),
            RateBand("offpeak", Decimal("0.20")),
        ),
    ),
    "T-FLAT-FIT": TariffSpec(
        code="T-FLAT-FIT",
        version=CATALOGUE_VERSION,
        supply_per_day=Decimal("1.10"),
        import_bands=(RateBand("flat", Decimal("0.30")),),
        export_credit_per_kwh=Decimal("0.05"),
    ),
    "T-FLAT-FIT-V2": TariffSpec(
        code="T-FLAT-FIT-V2",
        version=CATALOGUE_VERSION,
        supply_per_day=Decimal("1.10"),
        import_bands=(RateBand("flat", Decimal("0.35")),),
        export_credit_per_kwh=Decimal("0.05"),
    ),
}
