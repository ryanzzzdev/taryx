"""Characterisation of the independently deployed legacy calculator.

These fixtures record the legacy engine's *observed* behaviour — the
heritage GST exemption and the FIT-TRUNC-2003 export truncation defect
are documented here as differences, not judged correct. The legacy sim
is launched as a real subprocess over HTTP; it shares no code with the
core engine.
"""

import json
import socket
import subprocess
import sys
import time
import urllib.request
from decimal import Decimal
from pathlib import Path

import pytest

from taryx.core.migration.legacy_adapter import (
    PROTOCOL,
    LegacyFailure,
    build_request,
    calculate,
)

ROOT = Path(__file__).resolve().parent.parent
SIM = ROOT / "legacy-sim" / "legacy_sim.py"
DAY = "2026-03-02"


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _spawn(port: int, db_dir: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, str(SIM), "--port", str(port), "--db", str(db_dir / "calc.db")],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
            return proc
        except Exception:
            if proc.poll() is not None:
                msg = f"legacy-sim exited: {proc.stdout.read()}"
                raise RuntimeError(msg) from None
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("legacy-sim did not become healthy")


@pytest.fixture(scope="module")
def legacy(tmp_path_factory):
    port = _free_port()
    proc = _spawn(port, tmp_path_factory.mktemp("legacydb"))
    yield f"http://127.0.0.1:{port}", proc
    proc.kill()


def _set_fault(base_url: str, mode: str) -> None:
    req = urllib.request.Request(
        f"{base_url}/_admin/fault",
        data=json.dumps({"mode": mode}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=5)


def _records(channel: int, suffix: str, direction: str, value: str) -> dict:
    """48 interval-end records: 00:30..24:00 NEM time on DAY."""
    records = []
    for i in range(48):
        minutes = (i + 1) * 30
        if minutes == 1440:
            end = "2026-03-03T00:00:00+10:00"
        else:
            end = f"2026-03-02T{minutes // 60:02d}:{minutes % 60:02d}:00+10:00"
        records.append(
            {
                "end": end,
                "date": DAY,
                "value": value,
                "quality": "A",
                "record_id": channel * 100 + i,
            }
        )
    return {
        "channel_id": channel,
        "suffix": suffix,
        "direction": direction,
        "records": records,
    }


def _request(tariff_code: str, e1="0.5", b1="0.2", account="ACC-001") -> dict:
    return {
        "protocol": PROTOCOL,
        "snapshot_hash": f"test-{account}-{tariff_code}-{e1}-{b1}",
        "account": account,
        "period": [DAY, "2026-03-03"],
        "agreements": [
            {
                "id": 1,
                "tariff_code": tariff_code,
                "version": 1,
                "effective_from": "2026-01-01",
                "effective_to": None,
            }
        ],
        "channels": [
            _records(1, "E1", "import", e1),
            _records(2, "B1", "export", b1),
        ],
    }


def _line(result, element, band=None):
    return [line for line in result.lines if line.element == element and line.band == band][0]


def test_flat_fit_exposes_fit_trunc_defect(legacy):
    """B1 9.6 kWh/day: legacy truncates to 9 kWh → −0.45, not −0.48."""
    result = calculate(_request("T-FLAT-FIT"), base_url=legacy[0], timeout=5)
    assert result.engine_version == "1.0.0"
    imp = _line(result, "import", "flat")
    assert (imp.quantity, imp.amount, imp.gst) == (
        Decimal("24.0"),
        Decimal("7.20"),
        Decimal("0.72"),
    )
    exp = _line(result, "export_credit")
    assert (exp.quantity, exp.amount, exp.gst) == (
        Decimal("9"),
        Decimal("-0.45"),
        Decimal("0"),
    )
    assert (result.net, result.gst, result.total) == (
        Decimal("7.85"),
        Decimal("0.83"),
        Decimal("8.68"),
    )


def test_heritage_tariff_is_gst_exempt(legacy):
    """ACC-003 heritage agreement: legacy honours the pre-GST exemption."""
    result = calculate(
        _request("T-FLAT-FIT-HERITAGE", e1="0.4", b1="0.23", account="ACC-003"),
        base_url=legacy[0],
        timeout=5,
    )
    assert all(line.gst == Decimal("0") for line in result.lines)
    exp = _line(result, "export_credit")
    # Both differences present: exempt GST and truncated 11.04 → 11 kWh.
    assert (exp.quantity, exp.amount) == (Decimal("11"), Decimal("-0.55"))
    assert (result.net, result.gst, result.total) == (
        Decimal("7.27"),
        Decimal("0"),
        Decimal("7.27"),
    )


def test_integral_export_hides_the_defect(legacy):
    """Characterisation: the defect only fires on non-integral totals."""
    result = calculate(_request("T-FLAT-FIT", b1="0.25"), base_url=legacy[0], timeout=5)
    assert _line(result, "export_credit").quantity == Decimal("12")


def test_build_request_maps_snapshot_payload(legacy):
    payload = {
        "account": "ACC-001",
        "period": [DAY, "2026-03-03"],
        "agreements": [
            {
                "id": 7,
                "tariff_code": "T-FLAT-FIT",
                "version": 2,
                "effective_from": "2026-01-01",
                "effective_to": None,
            }
        ],
        "channels": [
            {
                "channel_id": 3,
                "suffix": "E1",
                "direction": "import",
                "records": [["2026-03-02T00:30:00+00:00", "0.5", "A", 11, "2026-03-02"]],
            }
        ],
        "tariffs": {"T-FLAT-FIT": {"should": "not be sent"}},
        "quarantines": [],
    }
    request = build_request(payload, "abc123")
    assert request["protocol"] == PROTOCOL
    assert request["snapshot_hash"] == "abc123"
    assert "tariffs" not in request
    assert request["channels"][0]["records"] == [
        {
            "end": "2026-03-02T00:30:00+00:00",
            "value": "0.5",
            "quality": "A",
            "record_id": 11,
            "date": "2026-03-02",
        }
    ]
    assert request["agreements"][0]["id"] == 7


def test_unknown_tariff_is_legacy_error(legacy):
    with pytest.raises(LegacyFailure, match="unknown_tariff") as info:
        calculate(_request("T-NOPE"), base_url=legacy[0], timeout=5)
    assert info.value.code == "legacy_error"


def test_timeout_is_inconclusive(legacy):
    base_url, _ = legacy
    _set_fault(base_url, "timeout")
    try:
        with pytest.raises(LegacyFailure) as info:
            calculate(_request("T-FLAT-FIT", b1="0.25"), base_url=base_url, timeout=1)
        assert info.value.code == "timeout"
    finally:
        _set_fault(base_url, "ok")


def test_malformed_response_is_inconclusive(legacy):
    base_url, _ = legacy
    _set_fault(base_url, "malformed")
    try:
        with pytest.raises(LegacyFailure) as info:
            calculate(_request("T-FLAT-FIT", b1="0.3"), base_url=base_url, timeout=5)
        assert info.value.code == "malformed"
    finally:
        _set_fault(base_url, "ok")


def test_unavailable_is_inconclusive(legacy):
    base_url, _ = legacy
    _set_fault(base_url, "unavailable")
    try:
        with pytest.raises(LegacyFailure) as info:
            calculate(_request("T-FLAT-FIT", b1="0.35"), base_url=base_url, timeout=5)
        assert info.value.code == "unavailable"
    finally:
        _set_fault(base_url, "ok")


def test_wrong_protocol_version_is_rejected(legacy):
    base_url, _ = legacy
    _set_fault(base_url, "wrong_protocol")
    try:
        with pytest.raises(LegacyFailure) as info:
            calculate(_request("T-FLAT-FIT", b1="0.4"), base_url=base_url, timeout=5)
        assert info.value.code == "version_mismatch"
    finally:
        _set_fault(base_url, "ok")


def test_restart_clears_faults_and_preserves_identity(tmp_path):
    port = _free_port()
    db_dir = tmp_path / "restart"
    proc = _spawn(port, db_dir)
    base_url = f"http://127.0.0.1:{port}"
    try:
        request = _request("T-FLAT-FIT", b1="0.45")
        before = calculate(request, base_url=base_url, timeout=5)
        _set_fault(base_url, "unavailable")
        proc.kill()
        proc.wait(timeout=5)
        proc = _spawn(port, db_dir)  # same db survives the restart
        after = calculate(request, base_url=base_url, timeout=5)
        # Same snapshot → identical deterministic lines; fault flag cleared.
        assert after.lines == before.lines
        assert after.snapshot_hash == before.snapshot_hash
        assert after.request_id != before.request_id
        # The legacy schema (sqlite calc log) persisted across the restart.
        log = json.loads(urllib.request.urlopen(f"{base_url}/_admin/log", timeout=5).read())
        assert [e["request_hash"] for e in log["entries"]] == [request["snapshot_hash"]]
    finally:
        proc.kill()
