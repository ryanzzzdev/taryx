"""Versioned client for the independently deployed legacy calculator.

Protocol "taryx-legacy/1": the adapter maps a RatingRun input_snapshot
payload to the legacy request — it carries the raw inputs (account,
period, agreements by tariff code, interval records) but NOT the new
catalogue's tariff specs; the legacy engine resolves its own versioned
catalogue. Comparison therefore compares engines on equivalent data,
not merely different serialisations.

Failure taxonomy is stable: timeout | unavailable | malformed |
version_mismatch | legacy_error — all inconclusive outcomes, never a
successful comparison.
"""

import contextlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

PROTOCOL = "taryx-legacy/1"


class LegacyFailure(Exception):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


@dataclass(frozen=True)
class LegacyLine:
    element: str
    band: str | None
    tariff_code: str
    tariff_version: str
    agreement_id: int
    segment_from: date
    segment_to: date
    quantity: Decimal
    unit: str
    rate: Decimal
    amount: Decimal
    gst: Decimal
    basis: str


@dataclass(frozen=True)
class LegacyResult:
    engine: str
    engine_version: str
    catalogue_version: str
    snapshot_hash: str
    request_id: str
    lines: tuple[LegacyLine, ...]
    net: Decimal
    gst: Decimal
    total: Decimal

    @property
    def version_token(self) -> str:
        return f"{self.engine}:{self.engine_version}:{self.catalogue_version}"


def build_request(payload: dict, snapshot_hash: str) -> dict:
    """Map a stored rating input_snapshot payload to the v1 request.

    Tariff specs are deliberately omitted — the legacy engine applies
    its own catalogue, which is where its versions/defects live.
    """
    return {
        "protocol": PROTOCOL,
        "snapshot_hash": snapshot_hash,
        "account": payload["account"],
        "period": payload["period"],
        "agreements": [
            {
                "id": a["id"],
                "tariff_code": a["tariff_code"],
                "version": a["version"],
                "effective_from": a["effective_from"],
                "effective_to": a["effective_to"],
            }
            for a in payload["agreements"]
        ],
        "channels": [
            {
                "channel_id": c["channel_id"],
                "suffix": c["suffix"],
                "direction": c["direction"],
                "records": [
                    {
                        "end": r[0],
                        "value": r[1],
                        "quality": r[2],
                        "record_id": r[3],
                        # NEM12 trading date: interval 48 ends at 00:00 on
                        # the next civil day, so `end` alone cannot derive it.
                        "date": r[4],
                    }
                    for r in c["records"]
                ],
            }
            for c in payload["channels"]
        ],
    }


def _decimal(raw, field: str) -> Decimal:
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise LegacyFailure("malformed", f"{field} is not decimal: {raw!r}") from exc
    if not value.is_finite():
        raise LegacyFailure("malformed", f"{field} is not finite: {raw!r}")
    return value


def _parse_line(item) -> LegacyLine:
    """Strictly validate one response line; errors are raised as
    KeyError/TypeError/ValueError for _parse to wrap as malformed."""
    if not isinstance(item, dict):
        raise TypeError(f"line is not an object: {type(item).__name__}")
    element = item["element"]
    if not isinstance(element, str) or not element:
        raise TypeError(f"line element must be a non-empty string: {element!r}")
    band = item.get("band")
    if band is not None and not isinstance(band, str):
        raise TypeError(f"line band must be a string or null: {band!r}")
    tariff_code = item["tariff_code"]
    if not isinstance(tariff_code, str) or not tariff_code:
        raise TypeError(f"line tariff_code must be a non-empty string: {tariff_code!r}")
    tariff_version = item["tariff_version"]
    if not isinstance(tariff_version, str):
        raise TypeError(f"line tariff_version must be a string: {tariff_version!r}")
    unit = item["unit"]
    if not isinstance(unit, str) or not unit:
        raise TypeError(f"line unit must be a non-empty string: {unit!r}")
    basis = item.get("basis", "")
    if not isinstance(basis, str):
        raise TypeError(f"line basis must be a string: {basis!r}")
    segment = item["segment"]
    if (
        not isinstance(segment, list | tuple)
        or len(segment) != 2
        or not all(isinstance(d, str) for d in segment)
    ):
        raise TypeError(f"line segment must be a pair of ISO date strings: {segment!r}")
    return LegacyLine(
        element=element,
        band=band,
        tariff_code=tariff_code,
        tariff_version=tariff_version,
        agreement_id=int(item["agreement_id"]),
        segment_from=date.fromisoformat(segment[0]),
        segment_to=date.fromisoformat(segment[1]),
        quantity=_decimal(item["quantity"], "quantity"),
        unit=unit,
        rate=_decimal(item["rate"], "rate"),
        amount=_decimal(item["amount"], "amount"),
        gst=_decimal(item["gst"], "gst"),
        basis=basis,
    )


def _parse(result) -> LegacyResult:
    if not isinstance(result, dict):
        raise LegacyFailure("malformed", f"response is not an object: {type(result).__name__}")
    if result.get("protocol") != PROTOCOL:
        raise LegacyFailure(
            "version_mismatch", f"protocol {result.get('protocol')!r} != {PROTOCOL!r}"
        )
    if not isinstance(result.get("lines"), list):
        raise LegacyFailure(
            "malformed", f"lines must be a list: {type(result.get('lines')).__name__}"
        )
    try:
        lines = tuple(_parse_line(item) for item in result["lines"])
        net = _decimal(result["net"], "net")
        gst = _decimal(result["gst"], "gst")
        total = _decimal(result["total"], "total")
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise LegacyFailure("malformed", f"response shape invalid: {exc}") from exc
    try:
        if sum((item.amount for item in lines), Decimal(0)) != net:
            raise LegacyFailure("malformed", "net does not equal sum of line amounts")
        if sum((item.gst for item in lines), Decimal(0)) != gst:
            raise LegacyFailure("malformed", "gst does not equal sum of line gst")
        if net + gst != total:
            raise LegacyFailure("malformed", "total does not equal net + gst")
        meta = {
            key: result[key]
            for key in (
                "engine",
                "engine_version",
                "catalogue_version",
                "snapshot_hash",
                "request_id",
            )
        }
        if not all(isinstance(v, str) and v for v in meta.values()):
            raise TypeError("metadata values must be non-empty strings")
    except InvalidOperation as exc:
        raise LegacyFailure("malformed", f"reconciliation arithmetic failed: {exc}") from exc
    except (KeyError, TypeError) as exc:
        raise LegacyFailure("malformed", f"response metadata invalid: {exc}") from exc
    return LegacyResult(
        engine=meta["engine"],
        engine_version=meta["engine_version"],
        catalogue_version=meta["catalogue_version"],
        snapshot_hash=meta["snapshot_hash"],
        request_id=meta["request_id"],
        lines=lines,
        net=net,
        gst=gst,
        total=total,
    )


def _check_usage_completeness(request: dict, parsed: LegacyResult) -> None:
    """Requested import usage must be billed, not omitted.

    Lines carry no channel identity, so completeness is reconciled by
    quantity: import lines must cover exactly the metered kWh asked
    for. A response that omits usage components — or bills a fraction
    of them — is malformed, not a comparison discrepancy. Export credit
    is deliberately not reconciled here: catalogues legitimately
    truncate or omit feed-in tariffs, and that divergence is comparison
    evidence rather than a protocol defect.
    """
    required = Decimal(0)
    saw_import = False
    for channel in request.get("channels") or []:
        if channel.get("direction") != "import":
            continue
        saw_import = True
        for record in channel.get("records") or []:
            required += _decimal(record.get("value"), "channel record value")
    if not saw_import:
        return
    billed = sum((line.quantity for line in parsed.lines if line.element == "import"), Decimal(0))
    if billed != required:
        raise LegacyFailure(
            "malformed",
            f"import lines bill {billed} kWh of {required} kWh requested",
        )


def calculate(request: dict, *, base_url: str, timeout: float = 5.0) -> LegacyResult:
    """POST a v1 request; raise LegacyFailure on any inconclusive outcome."""
    body = json.dumps(request).encode()
    req = urllib.request.Request(
        f"{base_url}/v1/calculate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except TimeoutError as exc:
        raise LegacyFailure("timeout", f"legacy timed out after {timeout}s") from exc
    except urllib.error.HTTPError as exc:
        detail = ""
        with contextlib.suppress(Exception):
            detail = exc.read().decode()[:200]
        code = "legacy_error" if 400 <= exc.code < 500 else "unavailable"
        raise LegacyFailure(code, f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, ConnectionError, OSError) as exc:
        raise LegacyFailure("unavailable", str(exc)) from exc
    if status != 200:
        raise LegacyFailure("unavailable", f"HTTP {status}")
    try:
        result = json.loads(raw)
    except ValueError as exc:
        raise LegacyFailure("malformed", "response is not JSON") from exc
    parsed = _parse(result)
    if parsed.snapshot_hash != request.get("snapshot_hash"):
        raise LegacyFailure("malformed", "snapshot_hash echo mismatch")
    _check_usage_completeness(request, parsed)
    return parsed
