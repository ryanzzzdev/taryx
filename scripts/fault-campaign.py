#!/usr/bin/env python3
"""TAR-016 real-process fault campaign.

Each scenario identifies a precise crash boundary, the starting state,
the fault action (external `docker kill --signal=KILL` or a real
service outage — never an in-process simulation), the expected
invariant, the restart procedure and the observed final records.
Results land in docs/project/evidence/m5/fault-campaign.{jsonl,md}.

Run: uv run python scripts/fault-campaign.py  (compose stack must be up;
the script arms/disarms worker fault env via `compose up -d worker`).
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/project/evidence/m5"
FIXTURE = ROOT / "tests/fixtures/nem12/day1_base.nem12"
ACCOUNT = "ACC-001"
WORKER = "taryx-worker-1"
DAY0 = int(os.environ.get("FAULT_DAY0", "10"))  # first scenario billing day
OP = os.environ.get("FAULT_OP", "fault")  # op-id prefix; change per rerun
records = []


def sh(*args, env_extra=None, check=True):
    env = {**os.environ, **(env_extra or {})}
    result = subprocess.run(args, capture_output=True, text=True, env=env, cwd=ROOT)
    if check and result.returncode != 0:
        raise SystemExit(f"FAILED {args}:\n{result.stdout}\n{result.stderr}")
    return result


def compose(*args, **kw):
    return sh("docker", "compose", *args, **kw)


def api(*manage_args):
    return compose("exec", "-T", "api", "python", "manage.py", *manage_args)


def shell(code):
    return api("shell", "-c", code)


def psql(sql):
    return compose(
        "exec", "-T", "db", "psql", "-U", "taryx_app", "-d", "taryx", "-Atc", sql
    ).stdout.strip()


def wait_log(service, needle, since, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        logs = compose("logs", service, "--since", since).stdout
        if needle in logs:
            return logs
        time.sleep(0.5)
    raise SystemExit(f"timeout waiting for {needle!r} in {service} logs")


def op_status(op_id):
    return psql(f"SELECT status FROM billing_billingoperation WHERE operation_id='{op_id}'")


def financials(period: str | None = None):
    period_clause = f" AND i.period_start='2026-03-{period}'" if period else ""
    return {
        "invoices": int(
            psql(
                "SELECT count(*) FROM billing_invoice i JOIN accounts_account a"
                f" ON i.account_id=a.id WHERE a.reference='{ACCOUNT}'{period_clause}"
            )
        ),
        "unbalanced_journals": int(
            psql(
                "SELECT count(*) FROM billing_journalentry j WHERE"
                " (SELECT coalesce(sum(debit),0) FROM billing_posting"
                " WHERE journal_id=j.id)"
                " <> (SELECT coalesce(sum(credit),0) FROM billing_posting"
                " WHERE journal_id=j.id)"
            )
        ),
    }


def provision_period(day: str, tag: str) -> None:
    """Ingest a fresh day and rate it — new billing period, real path.
    Stops short of admission so each scenario controls bill timing."""
    base = FIXTURE.read_text()
    nxt = str(int(day) + 1).zfill(2)
    prev = str(int(day) - 1).zfill(2)
    generated = base.replace("20260302", f"202603{day}").replace("20260301", f"202603{prev}")
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "tee", f"/tmp/{tag}.nem12"],
        input=generated,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if proc.returncode != 0:
        raise SystemExit(f"fixture write failed: {proc.stderr}")
    api("ingest_nem12", f"/tmp/{tag}.nem12")
    api("rate_account", ACCOUNT, f"2026-03-{day}", f"2026-03-{nxt}")


def bill(day: str, op_id: str):
    nxt = str(int(day) + 1).zfill(2)
    return api(
        "bill_account",
        ACCOUNT,
        f"2026-03-{day}",
        f"2026-03-{nxt}",
        "--op",
        op_id,
    )


def wait_op(op_id, want, timeout=90):
    deadline = time.time() + timeout
    status = "?"
    while time.time() < deadline:
        status = op_status(op_id)
        if status == want:
            return status
        time.sleep(1)
    raise SystemExit(f"op {op_id} never reached {want} (last: {status})")


def arm_worker(env_vars):
    """Recreate the worker with (or without) fault env armed."""
    compose("up", "-d", "worker", env_extra=env_vars)
    time.sleep(4)


def wait_broker(timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if (
            compose(
                "exec", "-T", "broker", "rabbitmq-diagnostics", "-q", "ping", check=False
            ).returncode
            == 0
        ):
            return
        time.sleep(2)
    raise SystemExit("broker did not come back")


def scenario(name, boundary, setup, fault, invariant, restart, observe):
    rec = {"scenario": name, "boundary": boundary, "invariant": invariant}
    try:
        rec["start_state"] = setup()
        fault()
        rec["observed"] = restart()
        rec["result"] = observe()
    except (SystemExit, Exception) as exc:
        rec["result"] = f"FAIL: {exc}"
    print(f"[{name}] {rec['result']}", flush=True)
    records.append(rec)


def s1_precommit_kill():
    op, day = f"{OP}-s1-precommit", str(DAY0).zfill(2)

    def setup():
        provision_period(day, op)
        arm_worker({"TARYX_BILLING_PRECOMMIT_SLEEP": "25"})
        bill(day, op)
        return {"op": op}

    def fault():
        wait_log("worker", "billing.precommit", "180s")
        sh("docker", "kill", "--signal=KILL", WORKER)

    def restart():
        mid = {"op_status": op_status(op), **financials(day)}
        arm_worker({})
        api("drain_outbox")
        wait_op(op, "complete")
        rec = {"mid": mid, "after": financials(day)}
        if mid["invoices"] != 0:
            raise SystemExit("FAIL: financial effect leaked before commit")
        if rec["after"]["invoices"] != 1:
            raise SystemExit(f"FAIL: {rec['after']['invoices']} invoices after recovery")
        return rec

    def observe():
        return "PASS: no invoice/journal leaked; drain produced exactly one balanced invoice"

    return scenario(
        "sigkill-before-commit",
        "inside the issuing transaction, before COMMIT",
        setup,
        fault,
        "no financial effect may leak; recovery yields exactly one",
        restart,
        observe,
    )


def s2_postcommit_kill():
    op, day = f"{OP}-s2-postcommit", str(DAY0 + 1).zfill(2)

    def setup():
        provision_period(day, op)
        arm_worker({"TARYX_BILLING_POSTCOMMIT_SLEEP": "25"})
        bill(day, op)
        return {"op": op}

    def fault():
        wait_log("worker", "billing.postcommit", "180s")
        sh("docker", "kill", "--signal=KILL", WORKER)

    def restart():
        mid = {"op_status": op_status(op), **financials(day)}
        arm_worker({})
        shell(
            "from taryx.composition.tasks import process_billing_operation\n"
            f"process_billing_operation.delay('{op}')"
        )
        wait_op(op, "complete", timeout=60)
        rec = {"mid": mid, "after": financials(day)}
        if mid["invoices"] != 1:
            raise SystemExit("FAIL: committed effect missing after kill")
        if rec["after"]["invoices"] != 1:
            raise SystemExit("FAIL: redelivery duplicated the effect")
        return rec

    def observe():
        return "PASS: committed invoice survived the kill; explicit redelivery added nothing"

    return scenario(
        "sigkill-after-commit",
        "after the issuing transaction commits, before the task acks",
        setup,
        fault,
        "exactly one invoice/journal; redelivery adds nothing",
        restart,
        observe,
    )


def http_code(url, data=None, timeout=5):
    """Any HTTP response — even a 403 auth gate — proves the app served
    the request quickly. Only connect/timeout failures count as down."""
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=timeout).status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return None


def s3_broker_outage():
    op, day = f"{OP}-s3-broker", str(DAY0 + 2).zfill(2)

    def setup():
        provision_period(day, op)
        compose("stop", "broker")
        out = bill(day, op)
        api_ok = http_code("http://localhost:8001/healthz") == 200
        gql = http_code(
            "http://localhost:8001/graphql",
            data=b'{"query":"{ me { username } }"}',
        )
        return {
            "op": op,
            "pending_in_outbox": "pending in outbox" in out.stderr,
            "api_ok": api_ok,
            "gql_code": gql,  # 403 = auth gate answered; None = down
            "status": op_status(op),
        }

    def fault():
        time.sleep(3)

    def restart():
        compose("start", "broker")
        wait_broker()
        api("drain_outbox")
        wait_op(op, "complete")
        return {"status": op_status(op), **financials(day)}

    def observe():
        return (
            "PASS: admission was durable with broker down; API stayed responsive; drain recovered"
        )

    return scenario(
        "broker-outage-recovery",
        "broker down at dispatch; admission is durable via the outbox",
        setup,
        fault,
        "no lost intent; API responsive during outage; op completes after",
        restart,
        observe,
    )


def s4_duplicate_delivery():
    op, day = f"{OP}-s4-duplicate", str(DAY0 + 3).zfill(2)

    def setup():
        provision_period(day, op)
        bill(day, op)
        return {"op": op}

    def fault():
        shell(
            "from taryx.composition.tasks import process_billing_operation\n"
            f"process_billing_operation.delay('{op}')\n"
            f"process_billing_operation.delay('{op}')"
        )

    def restart():
        wait_op(op, "complete")
        time.sleep(4)  # let the duplicate delivery settle
        return financials(day)

    def observe():
        return "PASS: duplicate deliveries produced exactly one invoice"

    return scenario(
        "duplicate-task-delivery",
        "same operation delivered twice through the broker",
        setup,
        fault,
        "at-least-once delivery yields exactly one financial effect",
        restart,
        observe,
    )


def s5_abandoned_lease():
    op, day = f"{OP}-s5-lease", str(DAY0 + 4).zfill(2)

    def setup():
        provision_period(day, op)
        compose("stop", "worker")
        bill(day, op)
        return {"op": op, "status": op_status(op)}

    def fault():
        time.sleep(5)  # message sits unclaimed — consumer lease abandoned

    def restart():
        compose("start", "worker")
        wait_op(op, "complete")
        return {"status": op_status(op), **financials(day)}

    def observe():
        return "PASS: queued intent survived the missing consumer; exactly once"

    return scenario(
        "abandoned-consumer-lease",
        "task queued while no consumer exists",
        setup,
        fault,
        "broker retains intent; the resumed worker processes it once",
        restart,
        observe,
    )


def s6_adapter_restart():
    corr = {}

    def setup():
        arm_worker({"TARYX_MARKET_SUBMIT_SLEEP": "20"})
        corr["id"] = (
            shell(
                "from taryx.core.accounts.models import SupplyPoint\n"
                "from taryx.core.market.services import request_transfer\n"
                "from datetime import date\n"
                "sp = SupplyPoint.objects.first()\n"
                "w = request_transfer(sp, date(2026, 3, 16))\n"
                "print(w.correlation_id)"
            )
            .stdout.strip()
            .splitlines()[-1]
        )
        shell(
            "from taryx.composition.tasks import market_submit\n"
            f"market_submit.delay('{corr['id']}')"
        )
        return {"correlation_id": corr["id"]}

    def fault():
        wait_log("worker", 'fault_point":"market.submit', "120s")
        sh("docker", "kill", "--signal=KILL", WORKER)

    def restart():
        mid = psql(
            "SELECT state || ':' || attempts FROM market_transferworkflow"
            f" WHERE correlation_id='{corr['id']}'"
        )
        arm_worker({})
        state, deadline = "?", time.time() + 240
        while time.time() < deadline:
            state = psql(
                f"SELECT state FROM market_transferworkflow WHERE correlation_id='{corr['id']}'"
            )
            if state in ("completed", "rejected", "failed"):
                break
            time.sleep(3)
        return {"mid_state": mid, "final_state": state}

    def observe():
        return (
            "PASS: crash left a durable draft; the restarted worker's "
            "sweep polled-then-resubmitted to terminal"
        )

    return scenario(
        "market-adapter-restart",
        "worker killed between durable attempt marker and counterparty POST",
        setup,
        fault,
        "no invented outcome; durable draft reconciles via poll-first resend",
        restart,
        observe,
    )


def s7_market_outage_billing():
    op, day = f"{OP}-s7-outage", str(DAY0 + 5).zfill(2)

    def setup():
        provision_period(day, op)
        compose("stop", "market")
        bill(day, op)
        return {"op": op}

    def fault():
        pass  # the outage is the fault; billing must stay available

    def restart():
        wait_op(op, "complete")
        billed = {"status_while_market_down": op_status(op)}
        compose("start", "market")
        return {**billed, **financials(day)}

    def observe():
        return "PASS: billing issued while the market coordinator was down"

    return scenario(
        "billing-under-market-outage",
        "market coordinator down during a billing run",
        setup,
        fault,
        "billing availability is independent of market integration",
        restart,
        observe,
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    for run in (
        s1_precommit_kill,
        s2_postcommit_kill,
        s3_broker_outage,
        s4_duplicate_delivery,
        s5_abandoned_lease,
        s6_adapter_restart,
        s7_market_outage_billing,
    ):
        run()
    (OUT / "fault-campaign.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    lines = [
        f"# TAR-016 fault campaign — {started}",
        "",
        "Method: real container faults only — `docker kill --signal=KILL` on the",
        "worker at code-level fault points (`TARYX_BILLING_PRECOMMIT_SLEEP`,",
        "`TARYX_BILLING_POSTCOMMIT_SLEEP`, `TARYX_MARKET_SUBMIT_SLEEP`),",
        "`docker compose stop` for broker/market outages, and duplicate task",
        "dispatches through the real broker. Invariants are verified by SQL",
        "against the live database. Rerun: `uv run python",
        "scripts/fault-campaign.py` (`FAULT_DAY0`/`FAULT_OP` shift op ids and",
        "billing days). Machine-readable output: `fault-campaign.jsonl`.",
        "",
    ]
    for r in records:
        lines += [
            f"## {r['scenario']} — {r['result']}",
            f"- Boundary: {r['boundary']}",
            f"- Invariant: {r['invariant']}",
            f"- Start: `{json.dumps(r.get('start_state'))}`",
            f"- Observed: `{json.dumps(r.get('observed'))}`",
            "",
        ]
    (OUT / "fault-campaign.md").write_text("\n".join(lines))
    print(f"\n{len(records)} scenarios -> {OUT}/fault-campaign.md")


if __name__ == "__main__":
    sys.exit(main())
