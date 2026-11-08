"""HTTP transport for the synthetic `taryx-market/1` protocol.

Thin urllib client; failure taxonomy mirrors the adapter contract —
`MarketTransport` (timeout/unavailable, retryable) vs `MarketHttpError`
(protocol-visible status codes like 401/409) vs malformed bodies.
"""

import contextlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

PROTOCOL_VERSION = "1"


class MarketTransport(Exception):
    """Retryable transport failure: timeout, refused connection, reset."""


class MarketHttpError(Exception):
    """A non-2xx response the counterparty deliberately returned."""

    def __init__(self, status: int, detail: str):
        self.status = status
        super().__init__(detail)


class MarketMalformed(Exception):
    """A response that arrived but is not valid protocol JSON."""


@dataclass
class MarketClient:
    base_url: str
    token: str
    timeout: float = 5.0

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "taryx-market-version": PROTOCOL_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except TimeoutError as exc:
            raise MarketTransport(f"timeout after {self.timeout}s") from exc
        except urllib.error.HTTPError as exc:
            detail = ""
            with contextlib.suppress(Exception):
                detail = exc.read().decode()[:200]
            raise MarketHttpError(exc.code, f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            raise MarketTransport(str(exc)) from exc
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise MarketMalformed("response is not JSON") from exc

    def post(self, path: str, body: dict) -> dict:
        return self._call("POST", path, body)

    def get(self, path: str) -> dict:
        return self._call("GET", path)
