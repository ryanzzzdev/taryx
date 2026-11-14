"""Exercise install.sh control flow without touching Kubernetes."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[5]
with tempfile.TemporaryDirectory() as tmp:
    folder = Path(tmp)
    stub = folder / 'kubectl'
    stub.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$PROBE_TRACE"
case "$*" in
  *"wait --for=condition=complete job/migrate-aurora"*) exit 1 ;;
esac
case "$*" in *"apply -f -"*) cat >/dev/null ;; esac
exit 0
''')
    stub.chmod(0o755)
    trace = folder / 'trace'
    env = {**os.environ, 'PATH': f'{folder}:' + os.environ['PATH'], 'KUBECTL': str(stub), 'PROBE_TRACE': str(trace)}
    result = subprocess.run(['bash', 'deploy/k8s/install.sh', '--rollout'], cwd=ROOT, env=env, capture_output=True, text=True)
    calls = trace.read_text()
    assert result.returncode != 0
    assert 'delete job db-init broker-provision migrate-aurora migrate-southgrid' in calls
    assert 'rollout restart' not in calls
    print('PASS: failed migration wait exits nonzero before rollout restart; Jobs recreated')
    print(calls)
