#!/usr/bin/env python3
"""TAR-018 portfolio measurement — R1 billing batch + repeated ingest.

Budgets (features/metering-and-rating.md §Measurement profile):
- Billing run <= 2 s per account p95; R1 batch <= 5 min total.
- Ingest R1 <= 90 s wall clock (repeated here for the repetition profile).
- Stack memory <= 8 GiB during R1; no unbounded queue growth.

Uses the R1 estate seeded by scripts/measure-budgets.py (100 accounts,
April 2026 data, 180k intervals). Output:
docs/project/evidence/m5/portfolio-run.{jsonl,md}
"""

import importlib.util
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/project/evidence/m5"
_spec = importlib.util.spec_from_file_location("fault_campaign", ROOT / "scripts/fault-campaign.py")
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

stats_samples: list[dict] = []
queue_samples: list[int] = []
sampling = threading.Event()


def sample_loop():
    while sampling.is_set():
        out = fc.sh(
            "docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}", check=False
        ).stdout
        total = 0.0
        for _name, mem in (line.split(" ", 1) for line in out.splitlines() if "taryx" in line):
            m = re.match(r"([\d.]+)([A-Za-z]+)", mem.strip())
            if not m:
                continue
            v, unit = float(m.group(1)), m.group(2)
            total += v * {"B": 1e-9, "KiB": 1 / 1048576, "MiB": 1 / 1024, "GiB": 1.0}.get(unit, 0)
        stats_samples.append({"t": round(time.time() % 100000, 1), "stack_gib": round(total, 3)})
        q = fc.compose(
            "exec",
            "-T",
            "broker",
            "rabbitmqctl",
            "-q",
            "list_queues",
            "-p",
            "taryx",
            "messages",
            check=False,
        )
        depth = sum(int(x) for x in q.stdout.split() if x.isdigit())
        queue_samples.append(depth)
        time.sleep(3)


def pct(vals, q):
    vals = sorted(vals)
    return round(vals[min(len(vals) - 1, int(len(vals) * q))], 3) if vals else None


def _batch_stats_from_db(wall_s):
    rows = fc.psql(
        "SELECT extract(epoch from completed_at - created_at) FROM"
        " billing_billingoperation WHERE operation_id LIKE 'r1-bill-%'"
        " AND status='complete'"
    ).splitlines()
    lat = [float(x) for x in rows if x.strip()]
    invoices = int(
        fc.psql(
            "SELECT count(*) FROM billing_billingoperation WHERE"
            " operation_id LIKE 'r1-bill-%' AND invoice_id IS NOT NULL"
        )
    )
    unbalanced = int(
        fc.psql(
            "SELECT count(*) FROM (SELECT journal_id FROM"
            " billing_posting GROUP BY journal_id HAVING"
            " sum(debit) <> sum(credit)) d"
        )
    )
    rec = {
        "scenario": "r1-billing-batch",
        "accounts": 100,
        "period": "2026-04-01..2026-05-01 (30 days)",
        "batch_wall_s": round(wall_s, 1),
        "op_latency_s": {
            "n": len(lat),
            "p50": pct(lat, 0.5),
            "p95": pct(lat, 0.95),
            "max": round(max(lat), 3) if lat else None,
        },
        "invoices": invoices,
        "unbalanced_journals": unbalanced,
        "budget": {"per_account_p95_s": 2.0, "batch_s": 300},
        "result": "PASS"
        if lat and pct(lat, 0.95) <= 2.0 and wall_s <= 300 and len(lat) == 100
        else "FAIL",
    }
    print(
        f"[batch] {rec['result']} wall={rec['batch_wall_s']}s op_p95={rec['op_latency_s']['p95']}s",
        flush=True,
    )
    return rec


def phase_bill_batch():
    """Rate 30-day runs for 100 R1 accounts, then admit+enqueue all ops;
    per-account latency = op created_at -> completed_at."""
    done = int(
        fc.psql(
            "SELECT count(*) FROM billing_billingoperation WHERE"
            " operation_id LIKE 'r1-bill-%' AND status='complete'"
        )
    )
    if done == 100:
        # Already ran — reconstruct from op timestamps (rerun-safe).
        wall = float(
            fc.psql(
                "SELECT extract(epoch from max(completed_at) -"
                " min(created_at)) FROM billing_billingoperation WHERE"
                " operation_id LIKE 'r1-bill-%'"
            )
        )
        rec = _batch_stats_from_db(wall)
        rec["note"] = "reconstructed from persisted op timestamps (prior run)"
        return rec
    code = """
import json, time
from datetime import date
from taryx.composition.policy import policy
from taryx.core.accounts.models import Account
from taryx.core.pricing.services import rate_account
from taryx.core.billing.services import admit_issue
from taryx.core.migration.services import routing_for
from taryx.composition.tasks import process_billing_operation
p = policy()
rate_s = []
t_batch = time.perf_counter()
for i in range(1, 101):
    acc = Account.objects.get(reference=f'ACC-R1-{i:03d}')
    t0 = time.perf_counter()
    run = rate_account(acc, date(2026, 4, 1), date(2026, 5, 1),
                       tariffs=p.TARIFFS, gst_rate=p.GST_RATE,
                       policy_identity=p.POLICY_IDENTITY)
    rate_s.append(round(time.perf_counter() - t0, 3))
    op = admit_issue(acc, date(2026, 4, 1), date(2026, 5, 1), run,
                     f'r1-bill-{i:03d}', routing_resolver=routing_for)
    process_billing_operation.delay(op.operation_id)
print(json.dumps({"rate_s": rate_s, "batch_open_s": round(time.perf_counter() - t_batch, 1)}))
"""
    t0 = time.time()
    out = fc.shell(code).stdout
    payload = json.loads(out.strip().splitlines()[-1])
    # Wait for all ops to complete.
    deadline = time.time() + 600
    while time.time() < deadline:
        pending = int(
            fc.psql(
                "SELECT count(*) FROM billing_billingoperation WHERE"
                " operation_id LIKE 'r1-bill-%' AND status='pending'"
            )
        )
        if pending == 0:
            break
        time.sleep(3)
    wall = time.time() - t0
    rec = _batch_stats_from_db(wall)
    rec["rate_seconds"] = {
        "p50": pct(payload["rate_s"], 0.5),
        "p95": pct(payload["rate_s"], 0.95),
        "max": max(payload["rate_s"]),
    }
    rec["admit_dispatch_s"] = payload["batch_open_s"]
    return rec


def phase_ingest_repeats():
    """Two more R1 ingests on FRESH periods (May, June) — same 180k
    shape through the create path — for the repetition profile."""
    recs = []
    for label, month, value in (("may", 5, "0.55"), ("june", 6, "0.65")):
        days = [f"2026{month:02d}{d:02d}" for d in range(1, 31)]
        import os

        os.environ["R1_VALUE"] = value
        _s = importlib.util.spec_from_file_location("measure", ROOT / "scripts/measure-budgets.py")
        m = importlib.util.module_from_spec(_s)
        _s.loader.exec_module(m)
        content = m.r1_nem12(days)
        proc = subprocess.run(
            ["docker", "compose", "exec", "-T", "api", "tee", f"/tmp/r1-{label}.nem12"],
            input=content,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        if proc.returncode != 0:
            raise SystemExit(proc.stderr)
        t0 = time.perf_counter()
        out = fc.api("ingest_nem12", f"/tmp/r1-{label}.nem12").stdout
        wall = time.perf_counter() - t0
        recs.append(
            {
                "scenario": f"r1-ingest-repeat-{label}",
                "period": f"2026-{month:02d} (30 days, fresh)",
                "wall_s": round(wall, 1),
                "tail": out.strip().splitlines()[-1][:160],
                "result": "PASS" if wall <= 90 else "FAIL",
            }
        )
        print(f"[ingest {label}] {recs[-1]['result']} {recs[-1]['wall_s']}s", flush=True)
    return recs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    sampling.set()
    sampler = threading.Thread(target=sample_loop, daemon=True)
    sampler.start()
    recs = [phase_bill_batch(), *phase_ingest_repeats()]
    sampling.clear()
    sampler.join(timeout=5)
    summary = {
        "scenario": "resource-observation",
        "peak_stack_gib": max((s["stack_gib"] for s in stats_samples), default=None),
        "max_queue_depth": max(queue_samples, default=None),
        "samples": len(stats_samples),
        "budget": {"stack_gib": 8.0},
        "result": "PASS"
        if stats_samples and max(s["stack_gib"] for s in stats_samples) <= 8.0
        else "FAIL",
    }
    recs.append(summary)
    (OUT / "portfolio-run.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    lines = [f"# TAR-018 portfolio measurement — {started}", ""]
    for r in recs:
        lines += [
            f"## {r['scenario']} — {r['result']}",
            "```json",
            json.dumps(r, indent=2),
            "```",
            "",
        ]
    lines += [
        "### Queue depth samples (broker `celery` queue, 3 s cadence)",
        "",
        f"`{queue_samples}`",
        "",
        "### Stack memory samples (docker stats GiB, 3 s cadence)",
        "",
        f"`{[s['stack_gib'] for s in stats_samples]}`",
        "",
    ]
    (OUT / "portfolio-run.md").write_text("\n".join(lines))
    print(f"peak_mem={summary['peak_stack_gib']}GiB max_queue={summary['max_queue_depth']}")
    print(f"-> {OUT}/portfolio-run.md")


if __name__ == "__main__":
    sys.exit(main())
