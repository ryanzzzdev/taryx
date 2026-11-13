#!/usr/bin/env python3
"""TAR-016c frozen-budget measurements (reference environment).

Two budgets from features/metering-and-rating.md §Measurement profile:
- API read p95 <= 500 ms during R1 ingestion (180k intervals).
- Worker SIGKILL recovery <= 60 s with exactly one financial effect.

R1 ingest wall time is also recorded (<= 90 s budget, feeds TAR-018).
Output: docs/project/evidence/m5/budget-runs.{jsonl,md}
Run: uv run python scripts/measure-budgets.py
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/project/evidence/m5"
_spec = importlib.util.spec_from_file_location("fault_campaign", ROOT / "scripts/fault-campaign.py")
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

R1_NMIS = [f"420000{i + 1:04d}" for i in range(100)]  # 4200000001..4200000100
B1_NMIS = set(R1_NMIS[::4])  # 25% carry an export channel
R1_DAYS = [f"202604{d:02d}" for d in range(1, 31)]
R1_VALUE = os.environ.get("R1_VALUE", "0.5")  # vary per rerun — content-hash differs
# Revisions must carry a LATER load/update stamp to out-rank the prior
# records (equal precedence + different value is a real quarantine).
R1_STAMP = os.environ.get("R1_STAMP", "20260331120000")


def seed_r1_accounts():
    """100 accounts (ACC-R1-001..100) via the real seed path."""
    fc.shell(
        "from taryx.core.accounts.seed import seed_demo_data\n"
        "from datetime import date\n"
        "specs = [\n"
        "    (f'ACC-R1-{i:03d}', f'R1 Customer {i:03d}', f'420000{i:04d}',\n"
        "     [('E1', 'import')] + ([('B1', 'export')] if i % 4 == 1 else []),\n"
        "     [('T-FLAT-FIT', date(2026, 1, 1), None)])\n"
        "    for i in range(1, 101)\n"
        "]\n"
        "print('seeded', len(seed_demo_data(specs)))"
    )


def r1_nem12(days: list[str] | None = None) -> str:
    vals = ",".join([R1_VALUE] * 48)
    lines = ["100,NEM12,20260430120000,TARYX,TARYX"]
    for nmi in R1_NMIS:
        for suffix in ("E1", "B1"):
            if suffix == "B1" and nmi not in B1_NMIS:
                continue
            lines.append(f"200,{nmi},E1B1,,{suffix},NEM100,1000001,kWh,30,")
            for day in days or R1_DAYS:
                lines.append(f"300,{day},{vals},A,,,{R1_STAMP},{R1_STAMP}")
    lines.append("900")
    return "\n".join(lines) + "\n"


def probe(url):
    t0 = time.perf_counter()
    try:
        urllib.request.urlopen(url, timeout=10).read()
        return time.perf_counter() - t0
    except Exception:
        return None


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    return round(sorted_vals[min(len(sorted_vals) - 1, int(len(sorted_vals) * q))] * 1000, 1)


def phase_ingest():
    """R1 ingest while polling /healthz (SELECT 1) and /metrics (aggregate
    queries); p95 must stay <= 500 ms."""
    print("[ingest] seeding 100 R1 accounts", flush=True)
    seed_r1_accounts()
    payload = r1_nem12()
    intervals = payload.count("\n300,") * 48
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "tee", "/tmp/r1.nem12"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if proc.returncode != 0:
        raise SystemExit(f"fixture write failed: {proc.stderr}")

    base = {
        u: [probe(u) for _ in range(6)]
        for u in ("http://localhost:8001/healthz", "http://localhost:8001/metrics")
    }
    print(f"[ingest] starting R1 ingest ({intervals} intervals)", flush=True)
    ing = subprocess.Popen(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "python",
            "manage.py",
            "ingest_nem12",
            "/tmp/r1.nem12",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=ROOT,
    )
    t0 = time.perf_counter()
    samples = {"healthz": [], "metrics": []}
    while ing.poll() is None:
        for name in ("healthz", "metrics"):
            dt = probe(f"http://localhost:8001/{name}")
            if dt is not None:
                samples[name].append(dt)
        time.sleep(0.06)
    wall = time.perf_counter() - t0
    out = ing.stdout.read()
    rec = {
        "scenario": "r1-ingest-api-p95",
        "intervals": intervals,
        "ingest_seconds": round(wall, 1),
        "ingest_tail": out.strip().splitlines()[-1][:200] if out.strip() else "",
        "budget": {"api_p95_ms": 500, "ingest_s": 90},
    }
    for name, vals in samples.items():
        vals = sorted(vals)
        rec[name] = {
            "n": len(vals),
            "p50_ms": pct(vals, 0.5),
            "p95_ms": pct(vals, 0.95),
            "max_ms": round(vals[-1] * 1000, 1) if vals else None,
            "baseline_p95_ms": pct(
                sorted(v for v in base[f"http://localhost:8001/{name}"] if v), 0.95
            ),
        }
    ok = wall <= 90 and all(
        rec[n]["p95_ms"] is not None and rec[n]["p95_ms"] <= 500 for n in samples
    )
    rec["result"] = "PASS" if ok else "FAIL"
    print(
        f"[ingest] {rec['result']} wall={rec['ingest_seconds']}s "
        f"healthz_p95={rec['healthz']['p95_ms']}ms metrics_p95={rec['metrics']['p95_ms']}ms",
        flush=True,
    )
    return rec


def phase_kill_recovery():
    """SIGKILL at the pre-commit boundary; time kill -> recovered complete."""
    op, day = "budget-kill", "26"
    fc.provision_period(day, op)
    fc.arm_worker({"TARYX_BILLING_PRECOMMIT_SLEEP": "30"})
    fc.bill(day, op)
    fc.wait_log("worker", "billing.precommit", "180s")
    t0 = time.perf_counter()
    fc.sh("docker", "kill", "--signal=KILL", fc.WORKER)
    fc.arm_worker({})
    fc.api("drain_outbox")
    fc.wait_op(op, "complete", timeout=60)
    elapsed = time.perf_counter() - t0
    fin = fc.financials(day)
    rec = {
        "scenario": "sigkill-recovery-budget",
        "kill_to_complete_s": round(elapsed, 1),
        "budget_s": 60,
        "op": op,
        **fin,
        "result": "PASS"
        if elapsed <= 60 and fin["invoices"] == 1 and fin["unbalanced_journals"] == 0
        else "FAIL",
    }
    print(
        f"[kill-recovery] {rec['result']} {rec['kill_to_complete_s']}s invoices={fin['invoices']}",
        flush=True,
    )
    return rec


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    recs = [phase_ingest(), phase_kill_recovery()]
    (OUT / "budget-runs.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    lines = [
        f"# TAR-016 frozen-budget runs — {started}",
        "",
        "Reference environment per features/metering-and-rating.md "
        "§Measurement profile (14-core, ~30 GiB RAM, Docker/Compose on NVMe).",
        "Probes: `/healthz` issues `SELECT 1`; `/metrics` runs status-count "
        "aggregations. SIGKILL recovery is timed from `docker kill` to op",
        "complete via the documented procedure (restart worker + drain outbox).",
        "",
    ]
    for r in recs:
        lines += [
            f"## {r['scenario']} — {r['result']}",
            "```json",
            json.dumps(r, indent=2),
            "```",
            "",
        ]
    (OUT / "budget-runs.md").write_text("\n".join(lines))
    print(f"\n-> {OUT}/budget-runs.md")


if __name__ == "__main__":
    sys.exit(main())
