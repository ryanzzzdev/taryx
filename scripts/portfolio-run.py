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

import calendar
import importlib.util
import json
import os
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
phase = "startup"  # tag each resource sample with the running phase


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
        stats_samples.append(
            {"t": round(time.time() % 100000, 1), "phase": phase, "stack_gib": round(total, 3)}
        )
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


def _batch_stats_from_db(op_like, expect, period, wall_s, rate_s):
    """Whole-run per-account latency = rating + issue (op created_at ->
    completed_at). The gate requires the financial invariants too:
    `expect` invoices and zero unbalanced journals — a fast batch that
    billed nothing is a FAIL, not a PASS."""
    rows = fc.psql(
        "SELECT extract(epoch from completed_at - created_at) FROM"
        f" billing_billingoperation WHERE operation_id LIKE '{op_like}'"
        " AND status='complete' ORDER BY operation_id"
    ).splitlines()
    op_lat = [float(x) for x in rows if x.strip()]
    whole = sorted(r + o for r, o in zip(rate_s, op_lat, strict=False))
    invoices = int(
        fc.psql(
            "SELECT count(*) FROM billing_billingoperation WHERE"
            f" operation_id LIKE '{op_like}' AND invoice_id IS NOT NULL"
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
        "accounts": expect,
        "period": period,
        "batch_wall_s": round(wall_s, 1),
        "whole_run_s": {
            "n": len(whole),
            "p50": pct(whole, 0.5),
            "p95": pct(whole, 0.95),
            "max": round(max(whole), 3) if whole else None,
        },
        "rate_seconds": {
            "p50": pct(rate_s, 0.5),
            "p95": pct(rate_s, 0.95),
            "max": max(rate_s) if rate_s else None,
        },
        "invoices": invoices,
        "unbalanced_journals": unbalanced,
        "budget": {"per_account_p95_s": 2.0, "batch_s": 300},
        "result": "PASS"
        if len(whole) == expect
        and pct(whole, 0.95) <= 2.0
        and wall_s <= 300
        and invoices == expect
        and unbalanced == 0
        else "FAIL",
    }
    print(
        f"[batch] {rec['result']} wall={rec['batch_wall_s']}s "
        f"whole_p95={rec['whole_run_s']['p95']}s invoices={invoices}",
        flush=True,
    )
    return rec


BILL_MONTH = int(os.environ.get("BILL_MONTH", "4"))
BILL_TAG = os.environ.get("BILL_TAG", "r1")


def phase_bill_batch():
    """Fresh identified batch every run: rate + admit + process 100
    accounts for BILL_MONTH. Re-running the same month/tag would only
    re-observe a prior batch, so it refuses and asks for a fresh tag."""
    op_like = f"{BILL_TAG}-bill-m{BILL_MONTH}-%"
    done = int(
        fc.psql(
            "SELECT count(*) FROM billing_billingoperation WHERE"
            f" operation_id LIKE '{op_like}' AND status='complete'"
        )
    )
    if done:
        return {
            "scenario": "r1-billing-batch",
            "result": "FAIL",
            "reason": f"{done} ops already complete for {op_like!r} — "
            "a rerun cannot measure a fresh batch; pick a new BILL_MONTH "
            "or BILL_TAG (data must be ingested for the month first)",
        }
    period = f"2026-{BILL_MONTH:02d}"
    n_y, n_m = (2027, 1) if BILL_MONTH == 12 else (2026, BILL_MONTH + 1)
    p_end = f"date({n_y}, {n_m}, 1)"
    code = f"""
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
t0 = time.time()
for i in range(1, 101):
    acc = Account.objects.get(reference=f'ACC-R1-{{i:03d}}')
    t = time.perf_counter()
    run = rate_account(acc, date(2026, {BILL_MONTH}, 1), {p_end},
                       tariffs=p.TARIFFS, gst_rate=p.GST_RATE,
                       policy_identity=p.POLICY_IDENTITY)
    rate_s.append(round(time.perf_counter() - t, 3))
    op = admit_issue(acc, date(2026, {BILL_MONTH}, 1), {p_end}, run,
                     f'{BILL_TAG}-bill-m{BILL_MONTH}-{{i:03d}}',
                     routing_resolver=routing_for)
    process_billing_operation.delay(op.operation_id)
print(json.dumps({{"rate_s": rate_s, "t0": t0}}))
"""
    out = fc.shell(code).stdout
    payload = json.loads(out.strip().splitlines()[-1])
    deadline = time.time() + 600
    while time.time() < deadline:
        pending = int(
            fc.psql(
                "SELECT count(*) FROM billing_billingoperation WHERE"
                f" operation_id LIKE '{op_like}' AND status='pending'"
            )
        )
        if pending == 0:
            break
        time.sleep(3)
    else:
        return {
            "scenario": "r1-billing-batch",
            "result": "FAIL",
            "reason": "ops still pending after 600 s",
        }
    wall = (
        float(
            fc.psql(
                "SELECT extract(epoch from max(completed_at)) FROM"
                f" billing_billingoperation WHERE operation_id LIKE '{op_like}'"
            )
        )
        - payload["t0"]
    )
    return _batch_stats_from_db(op_like, 100, f"{period}-01..{period}-30", wall, payload["rate_s"])


REPEAT_MONTHS = os.environ.get("REPEAT_MONTHS", "5,6")  # fresh periods; bump on rerun


def phase_ingest_repeats():
    """Two more R1 ingests on fresh periods (REPEAT_MONTHS, default
    May/June) — same 180k shape. Reruns become revisions via a fresh
    stamp, or pick new months for the fresh-create path."""
    months = [int(m) for m in REPEAT_MONTHS.split(",")]
    recs = []
    for label, month in ((f"m{m:02d}", m) for m in months):
        value = f"0.{month}5"
        days = [
            f"2026{month:02d}{d:02d}" for d in range(1, calendar.monthrange(2026, month)[1] + 1)
        ]
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
        # Per-batch outcome, not just wall: a rejected/duplicate/
        # quarantined batch is a FAIL even when fast.
        expected = content.count("\n300,") * 48
        status, selected, quarantined = m.ingest_outcome(out)
        recs.append(
            {
                "scenario": f"r1-ingest-repeat-{label}",
                "period": f"2026-{month:02d} (30 days)",
                "wall_s": round(wall, 1),
                "batch_status": status,
                "batch_selected": selected,
                "batch_quarantined": quarantined,
                "tail": out.strip().splitlines()[-1][:160],
                "result": "PASS"
                if wall <= 90
                and status == "published"
                and selected == expected
                and quarantined == 0
                else "FAIL",
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
    global phase
    phase = "bill"
    bill = phase_bill_batch()
    phase = "ingest"
    recs = [bill, *phase_ingest_repeats()]
    phase = "done"
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
    failed = [r["scenario"] for r in recs if r["result"] != "PASS"]
    if failed:
        print(f"FAILED: {failed}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
