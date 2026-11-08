"""Market coordinator simulator — independent satellite service.

Plays the counterparty in the synthetic `taryx-market/1` protocol
(decision 005): accepts idempotent transfer submissions, holds durable
workflow state in its own sqlite schema, and delivers outcome callbacks
to the adapter's `/callbacks/transfers` endpoint. Shares no code with
the core engine and has no core database credentials.

Scenarios (POST /_admin/scenario, deterministic per name):

- happy: completed callback after `delay` seconds.
- business-reject: rejected callback.
- duplicate-callback: completed callback sent twice.
- out-of-order-callback: a second (higher-seq) completed callback sent
  before the first.
- late-completion: completed callback sent after `delay` — set the
  delay past the adapter's outcome deadline to exercise reconciliation.
- lost-response: ack only; no callback is ever sent.
- malformed-callback: a schema-invalid callback body is sent.
- unavailable: no callback; combine with fault mode for submit-time
  failure instead.

Fault modes (POST /_admin/fault, in-memory, restart clears):

- ok: normal responses.
- unavailable: /transfers and /transfers/{id} return 503.
- timeout: requests hang past the client timeout.
- malformed-ack: /transfers returns a non-ack body.

POST /_admin/send_orphan emits a callback for an unknown correlation id.
"""

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROTOCOL = "taryx-market"
VERSION = "1"

SCENARIO = {"name": "happy", "delay": 0.2}
FAULT = {"mode": "ok"}
TOKEN = {"value": "taryx-market-token"}
CALLBACK_URL = {"default": ""}


def _db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS transfers(
               correlation_id TEXT PRIMARY KEY,
               nmi TEXT NOT NULL,
               effective_date TEXT NOT NULL,
               request_digest TEXT NOT NULL,
               status TEXT NOT NULL,
               last_seq INTEGER NOT NULL)"""
    )
    conn.commit()
    return conn


def _send(callback_url: str, payload: dict | str, delay: float = 0.0) -> None:
    body = payload if isinstance(payload, str) else json.dumps(payload)
    req = urllib.request.Request(
        callback_url,
        data=body.encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN['value']}",
            "taryx-market-version": VERSION,
        },
        method="POST",
    )
    if delay:
        time.sleep(delay)
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        print(f"callback delivery failed: {exc}", file=sys.stderr)


def _deliver(
    db_path: Path, url: str, correlation_id: str, payload: dict | str, delay: float
) -> None:
    _send(url, payload, delay)
    if isinstance(payload, dict) and payload.get("outcome") in {"completed", "rejected"}:
        # The coordinator's last-known status moves with the terminal
        # event it emitted — reconcile polls read this row.
        conn = _db(db_path)
        conn.execute(
            "UPDATE transfers SET status=?, last_seq=? WHERE correlation_id=?",
            (payload["outcome"], payload["seq"], correlation_id),
        )
        conn.commit()


def _schedule(db_path: Path, url: str, correlation_id: str, seq: int) -> None:
    name, delay = SCENARIO["name"], SCENARIO["delay"]
    base = {"correlation_id": correlation_id, "occurred_at": "2026-03-02T00:00:00Z"}
    deliveries: list[tuple[dict | str, float]] = []
    if name == "happy":
        deliveries = [({**base, "seq": seq, "outcome": "completed"}, delay)]
    elif name == "business-reject":
        deliveries = [({**base, "seq": seq, "outcome": "rejected"}, delay)]
    elif name == "duplicate-callback":
        deliveries = [
            ({**base, "seq": seq, "outcome": "completed"}, delay),
            ({**base, "seq": seq, "outcome": "completed"}, delay + 0.05),
        ]
    elif name == "out-of-order-callback":
        deliveries = [
            ({**base, "seq": seq + 1, "outcome": "completed"}, delay),
            ({**base, "seq": seq, "outcome": "completed"}, delay + 0.05),
        ]
    elif name == "late-completion":
        deliveries = [({**base, "seq": seq, "outcome": "completed"}, delay)]
    elif name == "lost-response":
        deliveries = []
    elif name == "malformed-callback":
        deliveries = [('{"correlation_id": "', delay)]
    for body, wait in deliveries:
        threading.Thread(
            target=_deliver,
            args=(db_path, url, correlation_id, body, wait),
            daemon=True,
        ).start()


class Handler(BaseHTTPRequestHandler):
    db_path: Path
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _read(self) -> tuple[dict | None, bytes]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            return json.loads(raw), raw
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, raw

    def _write(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorised(self) -> bool:
        if self.headers.get("taryx-market-version") != VERSION:
            self._write(400, {"error": "version_mismatch"})
            return False
        if self.headers.get("Authorization") != f"Bearer {TOKEN['value']}":
            self._write(401, {"error": "unauthorised"})
            return False
        return True

    def _faulted(self) -> bool:
        if FAULT["mode"] == "unavailable":
            self._write(503, {"error": "unavailable"})
            return True
        if FAULT["mode"] == "timeout":
            time.sleep(30)
            return True
        return False

    def do_GET(self):
        if self.path == "/healthz":
            self._write(200, {"status": "ok"})
            return
        if self.path == "/_admin/state":
            conn = _db(self.db_path)
            rows = conn.execute(
                "SELECT correlation_id,nmi,status,last_seq FROM transfers"
            ).fetchall()
            self._write(
                200,
                {
                    "transfers": [
                        dict(zip(("correlation_id", "nmi", "status", "last_seq"), r, strict=True))
                        for r in rows
                    ]
                },
            )
            return
        match = self.path.removeprefix("/transfers/")
        if match != self.path:
            if self._faulted() or not self._authorised():
                return
            conn = _db(self.db_path)
            row = conn.execute(
                "SELECT status,last_seq FROM transfers WHERE correlation_id=?",
                (match,),
            ).fetchone()
            if row is None:
                self._write(200, {"correlation_id": match, "status": "unknown", "last_seq": -1})
            else:
                self._write(200, {"correlation_id": match, "status": row[0], "last_seq": row[1]})
            return
        self._write(404, {"error": "not_found"})

    def do_POST(self):
        if self.path == "/_admin/scenario":
            body, _ = self._read()
            if isinstance(body, dict) and body.get("name"):
                SCENARIO.update({"name": body["name"], "delay": float(body.get("delay", 0.2))})
                self._write(200, {"ok": True})
            else:
                self._write(400, {"error": "bad_request"})
            return
        if self.path == "/_admin/fault":
            body, _ = self._read()
            if isinstance(body, dict) and body.get("mode") in {
                "ok",
                "unavailable",
                "timeout",
                "malformed-ack",
            }:
                FAULT["mode"] = body["mode"]
                self._write(200, {"ok": True})
            else:
                self._write(400, {"error": "bad_request"})
            return
        if self.path == "/_admin/send_orphan":
            body, _ = self._read()
            url = (body or {}).get("callback_url") or CALLBACK_URL["default"]
            threading.Thread(
                target=_send,
                args=(
                    url,
                    {
                        "correlation_id": str(uuid.uuid4()),
                        "seq": 1,
                        "outcome": "completed",
                        "occurred_at": "2026-03-02T00:00:00Z",
                    },
                ),
                daemon=True,
            ).start()
            self._write(200, {"ok": True})
            return
        if self.path != "/transfers":
            self._write(404, {"error": "not_found"})
            return
        if self._faulted() or not self._authorised():
            return
        body, _ = self._read()
        required = {"correlation_id", "nmi", "effective_date", "request_digest"}
        if not isinstance(body, dict) or not required.issubset(body):
            self._write(400, {"error": "bad_request"})
            return
        conn = _db(self.db_path)
        existing = conn.execute(
            "SELECT request_digest,status,last_seq FROM transfers WHERE correlation_id=?",
            (body["correlation_id"],),
        ).fetchone()
        if existing is not None:
            if existing[0] != body["request_digest"]:
                self._write(409, {"error": "digest_conflict"})
            else:
                self._write(
                    200,
                    {
                        "correlation_id": body["correlation_id"],
                        "status": "submitted",
                        "seq": existing[2],
                    },
                )
            return
        conn.execute(
            "INSERT INTO transfers VALUES(?,?,?,?,?,?)",
            (
                body["correlation_id"],
                body["nmi"],
                body["effective_date"],
                body["request_digest"],
                "submitted",
                0,
            ),
        )
        conn.commit()
        if FAULT["mode"] == "malformed-ack":
            self._write(200, {"surprise": True})
            return
        self._write(
            200, {"correlation_id": body["correlation_id"], "status": "submitted", "seq": 0}
        )
        url = body.get("callback_url") or CALLBACK_URL["default"]
        if url:
            _schedule(self.db_path, url, body["correlation_id"], 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--db", default="/data/market_sim.db")
    parser.add_argument("--token", default=os.environ.get("MARKET_TOKEN", "taryx-market-token"))
    parser.add_argument("--callback-url", default=os.environ.get("CALLBACK_URL", ""))
    args = parser.parse_args()
    TOKEN["value"] = args.token
    CALLBACK_URL["default"] = args.callback_url
    Handler.db_path = Path(args.db)
    Handler.db_path.parent.mkdir(parents=True, exist_ok=True)
    _db(Handler.db_path)
    print(f"market-sim listening on :{args.port}", file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
