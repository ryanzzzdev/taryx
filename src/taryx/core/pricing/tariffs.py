"""Tariff specification types for the frozen fictional-retailer profile.

Pure data: specifications are injected by territory/client policy packages;
core pricing never imports them (clients -> territories -> core).
"""

from dataclasses import dataclass
from datetime import time
from decimal import Decimal


@dataclass(frozen=True)
class RateBand:
    """A named import rate applying to intervals by NEM time-of-day of the
    interval END.

    ``window`` is (start_exclusive, end_inclusive) in NEM time; ``None``
    marks the catch-all band evaluated last (e.g. off-peak or flat).
    """

    name: str
    price: Decimal
    window: tuple[time, time] | None = None

    def covers(self, tod: time) -> bool:
        if self.window is None:
            return True
        start, end = self.window
        if start < end:
            return start < tod <= end
        return tod > start or tod <= end


@dataclass(frozen=True)
class TariffSpec:
    """A versioned fictional tariff: daily supply, import bands, optional
    export credit. Rates are GST-exclusive."""

    code: str
    version: str
    supply_per_day: Decimal
    import_bands: tuple[RateBand, ...]
    export_credit_per_kwh: Decimal | None = None
