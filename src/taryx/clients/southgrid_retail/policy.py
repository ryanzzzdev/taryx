"""Southgrid Retail — fictional retailer client policy.

Same tariff codes as the au_nem baseline (fixtures and agreements stay
shape-compatible) but different rates, FIT and catalogue identity, so
identical inputs price differently under the two clients.
"""

from datetime import date, time
from decimal import Decimal

from taryx.core.pricing.tariffs import RateBand, TariffSpec

CLIENT_ID = "southgrid_retail"
CLIENT_NAME = "Southgrid Retail"

CATALOGUE_VERSION = "2026-10-25.3-sg1"
POLICY_IDENTITY = f"southgrid-retail/au_nem-retail-catalogue/{CATALOGUE_VERSION}"
GST_RATE = Decimal("0.10")

_PEAK_WINDOW = (time(7, 0), time(22, 0))

TARIFFS: dict[str, TariffSpec] = {
    "T-FLAT": TariffSpec(
        code="T-FLAT",
        version=CATALOGUE_VERSION,
        supply_per_day=Decimal("1.25"),
        import_bands=(RateBand("flat", Decimal("0.34")),),
    ),
    "T-FLAT-V2": TariffSpec(
        code="T-FLAT-V2",
        version=CATALOGUE_VERSION,
        supply_per_day=Decimal("1.25"),
        import_bands=(RateBand("flat", Decimal("0.38")),),
    ),
    "T-TOU": TariffSpec(
        code="T-TOU",
        version=CATALOGUE_VERSION,
        supply_per_day=Decimal("1.25"),
        import_bands=(
            RateBand("peak", Decimal("0.45"), _PEAK_WINDOW),
            RateBand("offpeak", Decimal("0.18")),
        ),
    ),
    "T-FLAT-FIT": TariffSpec(
        code="T-FLAT-FIT",
        version=CATALOGUE_VERSION,
        supply_per_day=Decimal("1.25"),
        import_bands=(RateBand("flat", Decimal("0.34")),),
        export_credit_per_kwh=Decimal("0.08"),
    ),
    "T-FLAT-FIT-V2": TariffSpec(
        code="T-FLAT-FIT-V2",
        version=CATALOGUE_VERSION,
        supply_per_day=Decimal("1.25"),
        import_bands=(RateBand("flat", Decimal("0.38")),),
        export_credit_per_kwh=Decimal("0.08"),
    ),
    "T-FLAT-FIT-HERITAGE": TariffSpec(
        code="T-FLAT-FIT-HERITAGE",
        version=CATALOGUE_VERSION,
        supply_per_day=Decimal("0.95"),
        import_bands=(RateBand("flat", Decimal("0.42")),),
        export_credit_per_kwh=Decimal("0.08"),
        gst_exempt=True,
    ),
}

# Distinct accounts sharing the baseline's account references and NMIs:
# the overlap is deliberate — a cross-client lookup would return the
# wrong retailer's data under a valid-looking identifier.
DEMO_SPECS = [
    (
        "ACC-001",
        "Bayview Corner Store",
        "4102000001",
        [("E1", "import"), ("B1", "export")],
        [("T-FLAT-FIT", date(2026, 1, 1), None)],
    ),
    (
        "ACC-002",
        "Jetty Road Pharmacy",
        "4102000002",
        [("E1", "import")],
        [("T-TOU", date(2026, 1, 1), None)],
    ),
    (
        "ACC-003",
        "Marina Parade Cellars",
        "4102000003",
        [("E1", "import"), ("B1", "export")],
        [
            ("T-FLAT-FIT", date(2026, 1, 1), date(2026, 1, 15)),
            ("T-FLAT-FIT-HERITAGE", date(2026, 1, 15), None),
        ],
    ),
]
