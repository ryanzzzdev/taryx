"""Legacy billing calculator simulator — an independent satellite service.

Deliberately shares no code with the Taryx core engine: it has its own
catalogue ("L-2003.4"), its own arithmetic, and its own sqlite schema
(the legacy calc log). Deployed as a separate container with no core
database credentials; the only interface is the versioned HTTP protocol
"taryx-legacy/1".

Characterisation scenarios (fictional, seeded):

- Historical commitment — tariff T-FLAT-FIT-HERITAGE is a pre-GST
  heritage contract the legacy catalogue honours as GST-exempt. The new
  catalogue prices the same code with standard GST, so the divergence
  is a *policy* difference to preserve, not an engine defect.
- Seeded arithmetic defect FIT-TRUNC-2003 — the export-credit quantity
  is truncated to whole kWh per line before crediting, under-crediting
  customers whenever segment export totals are non-integral.

Fault injection (POST /_admin/fault) supports timeout, malformed,
unavailable and wrong_protocol modes for resilience characterisation;
flags are in-memory so a restart clears them while the sqlite calc log
persists across restarts.
"""

import argparse
import json
import sqlite3
import sys
import time
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROTOCOL = "taryx-legacy/1"
ENGINE = "legacy-sim/1.0.0"
CATALOGUE_VERSION = "L-2003.4"
NEM_TZ = timezone(timedelta(hours=10), name="NEM")
MONEY = Decimal("0.01")

# Legacy tariff catalogue: independent versions, deliberately seeded
# with the heritage GST exemption and the FIT-TRUNC-2003 defect.
CATALOGUE = {
    "T-FLAT": {
        "supply_per_day": Decimal("1.10"),
        "bands": [("flat", Decimal("0.30"), None)],
        "export_rate": None,
        "gst_exempt": False,
    },
    "T-FLAT-V2": {
        "supply_per_day": Decimal("1.10"),
        "bands": [("flat", Decimal("0.35"), None)],
        "export_rate": None,
        "gst_exempt": False,
    },
    "T-TOU": {
        "supply_per_day": Decimal("1.10"),
        "bands": [
            ("peak", Decimal("0.40"), ("07:00:00", "22:00:00")),
            ("offpeak", Decimal("0.20"), None),
        ],
        "export_rate": None,
        "gst_exempt": False,
    },
    "T-FLAT-FIT": {
        "supply_per_day": Decimal("1.10"),
        "bands": [("flat", Decimal("0.30"), None)],
        "export_rate": Decimal("0.05"),
        "gst_exempt": False,
    },
    "T-FLAT-FIT-V2": {
        "supply_per_day": Decimal("1.10"),
        "bands": [("flat", Decimal("0.35"), None)],
        "export_rate": Decimal("0.05"),
        "gst_exempt": False,
    },
    # Pre-GST heritage agreement: legacy honours the exemption.
    "T-FLAT-FIT-HERITAGE": {
        "supply_per_day": Decimal("1.10"),
        "bands": [("flat", Decimal("0.35"), None)],
        "export_rate": Decimal("0.05"),
        "gst_exempt": True,
    },
}
GST_RATE = Decimal("0.10")

FAULT = {"mode": "ok"}


class LegacyCalcError(Exception):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


def _d(value) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise LegacyCalcError("bad_request", f"not a decimal: {value!r}") from exc


def _money(v: Decimal) -> Decimal:
    return v.quantize(MONEY, rounding=ROUND_HALF_UP)


def _parse_record(rec: dict) -> tuple[date, datetime]:
    """(trading date, local end instant). Interval 48 ends at 00:00 on
    the next civil day, so the protocol carries the trading date —
    deriving it from `end` would be off by one."""
    try:
        end = datetime.fromisoformat(rec["end"])
        day = date.fromisoformat(rec["date"])
    except (KeyError, ValueError) as exc:
        raise LegacyCalcError("bad_request", f"bad interval record {rec!r}") from exc
    return day, end.astimezone(NEM_TZ)


def _covers(ag: dict, day: date) -> bool:
    start = date.fromisoformat(ag["effective_from"])
    end = date.fromisoformat(ag["effective_to"]) if ag["effective_to"] else None
    return start <= day and (end is None or day < end)


def _band(tariff: dict, tod) -> tuple[str, Decimal]:
    catch = None
    for name, price, window in tariff["bands"]:
        if window is None:
            catch = (name, price)
            continue
        start_h, end_h = (datetime.strptime(t, "%H:%M:%S").time() for t in window)
        if start_h < tod <= end_h:
            return name, price
    if catch is None:
        raise LegacyCalcError("uncovered_band", f"no band covers {tod}")
    return catch


def compute(request: dict) -> dict:
    if request.get("protocol") != PROTOCOL:
        raise LegacyCalcError("protocol_mismatch", f"expected {PROTOCOL}")
    agreements = request.get("agreements") or []
    channels = request.get("channels") or []
    # Materialise intervals once: (day, local_end, value) per channel.
    parsed = []
    for ch in channels:
        rows = [(*_parse_record(r), _d(r["value"])) for r in ch["records"]]
        parsed.append((ch, rows))
    days = sorted({day for _, rows in parsed for day, _, _ in rows})
    if not days:
        raise LegacyCalcError("bad_request", "request carries no intervals")

    # Map each day to its agreement; merge consecutive days per agreement.
    spans: list[tuple[dict, list[date]]] = []
    for day in days:
        covering = [a for a in agreements if _covers(a, day)]
        if len(covering) != 1:
            raise LegacyCalcError("missing_agreement", f"{len(covering)} agreements cover {day}")
        if spans and spans[-1][0]["id"] == covering[0]["id"]:
            spans[-1][1].append(day)
        else:
            spans.append((covering[0], [day]))

    lines: list[dict] = []

    def add(ag, tariff, seg_days, element, band, qty, unit, rate, basis, sign=1):
        amount = _money(Decimal(sign) * qty * rate)
        taxable = element in ("supply", "import") and not tariff["gst_exempt"]
        gst = _money(amount * GST_RATE) if taxable else Decimal("0")
        lines.append(
            {
                "element": element,
                "band": band,
                "tariff_code": ag["tariff_code"],
                "tariff_version": CATALOGUE_VERSION,
                "agreement_id": ag["id"],
                "segment": [seg_days[0].isoformat(), seg_days[-1].isoformat()],
                "quantity": str(qty),
                "unit": unit,
                "rate": str(rate),
                "amount": str(amount),
                "gst": str(gst),
                "basis": basis,
            }
        )

    for ag, seg_days in spans:
        tariff = CATALOGUE.get(ag["tariff_code"])
        if tariff is None:
            raise LegacyCalcError("unknown_tariff", f"no legacy spec for {ag['tariff_code']!r}")
        seg_set = set(seg_days)
        for ch, rows in parsed:
            items = [(tod, val) for day, tod, val in rows if day in seg_set]
            if not items:
                continue
            if ch["direction"] == "import":
                buckets: dict[tuple[str, Decimal], Decimal] = {}
                counts: dict[tuple[str, Decimal], int] = {}
                for tod, val in items:
                    key = _band(tariff, tod.time())
                    buckets[key] = buckets.get(key, Decimal(0)) + val
                    counts[key] = counts.get(key, 0) + 1
                for (name, price), qty in sorted(buckets.items()):
                    add(
                        ag,
                        tariff,
                        seg_days,
                        "import",
                        name,
                        qty,
                        "kWh",
                        price,
                        f"{counts[(name, price)]} interval values on "
                        f"{ch['suffix']} over {len(seg_days)} days",
                    )
            elif ch["direction"] == "export" and tariff["export_rate"] is not None:
                qty = sum((v for _, v in items), Decimal(0))
                # Seeded defect FIT-TRUNC-2003: export quantity truncated
                # to whole kWh per line before crediting.
                qty = qty.to_integral_value(rounding="ROUND_FLOOR")
                if qty:
                    add(
                        ag,
                        tariff,
                        seg_days,
                        "export_credit",
                        None,
                        qty,
                        "kWh",
                        tariff["export_rate"],
                        f"feed-in credit on {len(items)} interval values "
                        f"on {ch['suffix']} over {len(seg_days)} days",
                        sign=-1,
                    )
        add(
            ag,
            tariff,
            seg_days,
            "supply",
            None,
            Decimal(len(seg_days)),
            "day",
            tariff["supply_per_day"],
            f"daily supply charge over {len(seg_days)} days",
        )

    order = {"import": 0, "export_credit": 1, "supply": 2}
    lines.sort(key=lambda row: (row["segment"][0], order[row["element"]], row["band"] or ""))
    net = sum((_d(row["amount"]) for row in lines), Decimal(0))
    gst = sum((_d(row["gst"]) for row in lines), Decimal(0))
    return {
        "protocol": PROTOCOL,
        "engine": "legacy-sim",
        "engine_version": "1.0.0",
        "catalogue_version": CATALOGUE_VERSION,
        "snapshot_hash": request.get("snapshot_hash"),
        "request_id": str(uuid.uuid4()),
        "computed_at": datetime.now(UTC).isoformat(),
        "lines": lines,
        "net": str(net),
        "gst": str(gst),
        "total": str(net + gst),
    }


def _init_db(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, check_same_thread=False)
    db.execute(
        "CREATE TABLE IF NOT EXISTS calc_log ("
        " request_hash TEXT PRIMARY KEY,"
        " request_id TEXT NOT NULL,"
        " engine TEXT NOT NULL,"
        " computed_at TEXT NOT NULL,"
        " response TEXT NOT NULL)"
    )
    return db


class Handler(BaseHTTPRequestHandler):
    server_version = ENGINE

    def _json(self, code: int, body) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        try:
            return json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        except (ValueError, TypeError) as exc:
            raise LegacyCalcError("bad_request", "body is not JSON") from exc

    def do_GET(self):
        if self.path == "/healthz":
            return self._json(200, {"status": "ok", "engine": ENGINE})
        if self.path == "/v1/version":
            return self._json(
                200,
                {
                    "engine": ENGINE,
                    "protocol": PROTOCOL,
                    "catalogue_version": CATALOGUE_VERSION,
                    "tariffs": sorted(CATALOGUE),
                },
            )
        if self.path == "/_admin/log":
            rows = self.server.db.execute(
                "SELECT request_hash, request_id, engine, computed_at FROM calc_log"
                " ORDER BY computed_at"
            ).fetchall()
            keys = ("request_hash", "request_id", "engine", "computed_at")
            return self._json(200, {"entries": [dict(zip(keys, r, strict=True)) for r in rows]})
        self._json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path == "/_admin/fault":
            body = self._body()
            modes = {"ok", "timeout", "malformed", "unavailable", "wrong_protocol"}
            if body.get("mode") not in modes:
                return self._json(400, {"error": "unknown fault mode"})
            FAULT["mode"] = body["mode"]
            return self._json(200, {"mode": FAULT["mode"]})
        if self.path != "/v1/calculate":
            return self._json(404, {"error": "not_found"})

        mode = FAULT["mode"]
        if mode == "timeout":
            time.sleep(30)
        if mode == "unavailable":
            return self._json(503, {"error": "legacy unavailable"})
        if mode == "malformed":
            data = b'{"protocol":"taryx-leg'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        try:
            request = self._body()
            response = compute(request)
        except LegacyCalcError as exc:
            return self._json(422, {"error": exc.code, "detail": str(exc)})
        if mode == "wrong_protocol":
            response["protocol"] = "taryx-legacy/0"
        self.server.db.execute(
            "INSERT OR REPLACE INTO calc_log VALUES (?,?,?,?,?)",
            (
                request.get("snapshot_hash") or "",
                response["request_id"],
                ENGINE,
                response["computed_at"],
                json.dumps(response),
            ),
        )
        self.server.db.commit()
        self._json(200, response)

    def log_message(self, fmt, *args):
        sys.stderr.write("legacy-sim: " + fmt % args + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--db", type=Path, default=Path("/data/legacy_calc.db"))
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    server.db = _init_db(args.db)
    print(f"{ENGINE} listening on :{args.port} (db {args.db})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
