"""Run from repository root: python3 docs/project/evidence/m5/review-r1/probes.py.
These isolated probes demonstrate false-positive evidence without service mutations.
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

portfolio = load('portfolio-run')
with patch.object(portfolio.fc, 'psql', side_effect=['\n'.join(['0.1'] * 100), '0', '1']):
    result = portfolio._batch_stats_from_db(1)
    print('billing with zero invoices and unbalanced journal:', result['result'])
    assert result['result'] == 'PASS', 'False-positive fixed; update this regression probe'

fault = load('fault-campaign')
with patch.object(fault, 'provision_period'), patch.object(fault, 'bill'), patch.object(fault, 'shell'), patch.object(fault, 'wait_op'), patch.object(fault.time, 'sleep'), patch.object(fault, 'financials', return_value={'invoices': 2, 'unbalanced_journals': 1}):
    fault.s4_duplicate_delivery()
    result = fault.records[-1]
    print('duplicate campaign with two invoices/unbalanced journal:', result['result'])
    assert result['result'].startswith('PASS'), 'False-positive fixed; update probe'

measure = load('measure-budgets')
class FailedIngest:
    stdout = SimpleNamespace(read=lambda: 'ingestion failed')
    returncode = 1
    calls = 0
    def poll(self):
        self.calls += 1
        return None if self.calls == 1 else 1
with patch.object(measure, 'seed_r1_accounts'), patch.object(measure.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), patch.object(measure.subprocess, 'Popen', return_value=FailedIngest()), patch.object(measure, 'probe', return_value=0.001), patch.object(measure.time, 'sleep'):
    result = measure.phase_ingest()
    print('failed ingest:', result['result'], result['ingest_tail'])
    assert result['result'] == 'PASS', 'False-positive fixed; update probe'
