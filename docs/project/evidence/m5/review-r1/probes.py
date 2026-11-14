"""Run from repository root: python3 docs/project/evidence/m5/review-r1/probes.py.
Round-1 probes reproduced false-positive PASS gates (M5-F1/F2). After
remediation they assert the corrected behaviour: bad state must FAIL.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# F1a: zero invoices + unbalanced journal must FAIL, not PASS.
portfolio = load('portfolio-run')
with patch.object(portfolio.fc, 'psql', side_effect=['\n'.join(['0.1'] * 100), '0', '1']):
    result = portfolio._batch_stats_from_db('x-%', 100, 'p', 1, [0.05] * 100)
    print('billing with zero invoices and unbalanced journal:', result['result'])
    assert result['result'] == 'FAIL', 'gate still accepts missing invoices/unbalanced journals'

# F1b: duplicate-delivery observe() must FAIL on two invoices.
fault = load('fault-campaign')
observed = {'invoices': 2, 'unbalanced_journals': 1}
try:
    fault.s4_duplicate_delivery()['kwargs'] if False else None
except Exception:
    pass
# observe is a closure; exercise the shared invariant check directly.
try:
    fault.require_one_balanced_invoice(observed)
except SystemExit:
    print('duplicate campaign with two invoices/unbalanced journal: FAIL (correct)')
else:
    raise AssertionError('invariant check still accepts duplicate effects')

# F2: ingest subprocess failure must FAIL, not PASS.
measure = load('measure-budgets')
class FailedIngest:
    stdout = SimpleNamespace(read=lambda: 'ingestion failed')
    returncode = 1
    calls = 0
    def poll(self):
        self.calls += 1
        return None if self.calls == 1 else 1
with patch.object(measure, 'seed_r1_accounts'), \
     patch.object(measure.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
     patch.object(measure.subprocess, 'Popen', return_value=FailedIngest()), \
     patch.object(measure, 'probe', return_value=0.001), \
     patch.object(measure.fc, 'psql', return_value='180000'), \
     patch.object(measure.time, 'sleep'):
    result = measure.phase_ingest()
    print('failed ingest:', result['result'], result['ingest_tail'])
    assert result['result'] == 'FAIL', 'gate still ignores ingest exit code'
