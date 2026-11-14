"""Independent regression probes. Run: python3 docs/project/evidence/m5/review-r2/probes.py.
Mocked service responses isolate evidence-gate correctness; no services are mutated.
Failures identify remaining gaps, rather than asserting that buggy behaviour persists.
"""
import importlib.util
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class GateTests(unittest.TestCase):
    def ingest(self, output, rc=0, failed_http=False):
        m = load('measure-budgets')
        class Process:
            stdout = SimpleNamespace(read=lambda: output)
            returncode = rc
            calls = 0
            def poll(self):
                self.calls += 1
                return None if self.calls <= 2 else rc
        with ExitStack() as stack:
            for target, name, kw in [
                (m, 'seed_r1_accounts', {}),
                (m.subprocess, 'run', {'return_value': SimpleNamespace(returncode=0)}),
                (m.subprocess, 'Popen', {'return_value': Process()}),
                (m, 'probe', {'side_effect': ([0.001] * 12 + [None, 0.001, 0.001, 0.001]) if failed_http else None, 'return_value': 0.001}),
                (m.fc, 'psql', {'return_value': '540192'}),
                (m.time, 'sleep', {}),
            ]:
                stack.enter_context(patch.object(target, name, **kw))
            return m.phase_ingest()

    def test_ingest_nonzero_exit_rejected(self):
        self.assertEqual(self.ingest('failed', 1)['result'], 'FAIL')

    def test_http_failure_rejected(self):
        self.assertEqual(self.ingest('published', failed_http=True)['result'], 'FAIL')

    def test_rejected_batch_with_old_intervals_rejected(self):
        self.assertEqual(self.ingest('r1.nem12: rejected (unknown_nmi)')['result'], 'FAIL')

    def test_duplicate_batch_with_old_intervals_rejected(self):
        self.assertEqual(self.ingest('r1.nem12: duplicate')['result'], 'FAIL')

    def test_quarantined_batch_rejected(self):
        self.assertEqual(self.ingest('r1.nem12: published (180000 intervals, 0 selected, 180000 quarantined)')['result'], 'FAIL')

    def test_budget_main_returns_failure(self):
        m = load('measure-budgets')
        with tempfile.TemporaryDirectory() as out, patch.object(m, 'OUT', Path(out)), patch.object(m, 'phase_ingest', return_value={'scenario': 'ingest', 'result': 'FAIL'}), patch.object(m, 'phase_kill_recovery', return_value={'scenario': 'kill', 'result': 'PASS'}):
            self.assertEqual(m.main(), 1)

    def test_duplicate_scenario_enforces_invariant(self):
        f = load('fault-campaign')
        with ExitStack() as stack:
            for name in ('provision_period', 'bill', 'shell', 'wait_op', 'wait_queue_drained'):
                stack.enter_context(patch.object(f, name))
            stack.enter_context(patch.object(f, 'financials', return_value={'invoices': 2, 'unbalanced_journals': 1}))
            f.s4_duplicate_delivery()
            self.assertTrue(f.records[-1]['result'].startswith('FAIL'))

    def test_postcommit_waits_for_redelivery(self):
        f = load('fault-campaign')
        with ExitStack() as stack:
            for name in ('provision_period', 'arm_worker', 'bill', 'wait_log', 'sh', 'api', 'shell', 'wait_op'):
                stack.enter_context(patch.object(f, name))
            stack.enter_context(patch.object(f, 'op_status', return_value='complete'))
            stack.enter_context(patch.object(f, 'financials', return_value={'invoices': 1, 'unbalanced_journals': 0}))
            drain = stack.enter_context(patch.object(f, 'wait_queue_drained'))
            f.s2_postcommit_kill()
            self.assertTrue(drain.called, 'complete predates redelivery; observing it again cannot establish consumption')

    def test_billing_counts_and_balances_enforced(self):
        p = load('portfolio-run')
        with patch.object(p.fc, 'psql', side_effect=['\n'.join(['0.1'] * 100), '0', '1']):
            self.assertEqual(p._batch_stats_from_db('probe-%', 100, 'period', 1, [0.05] * 100)['result'], 'FAIL')

    def test_rating_included_in_budget(self):
        p = load('portfolio-run')
        with patch.object(p.fc, 'psql', side_effect=['\n'.join(['0.1'] * 100), '100', '0']):
            self.assertEqual(p._batch_stats_from_db('probe-%', 100, 'period', 1, [3] * 100)['result'], 'FAIL')

    def test_old_batch_not_reconstructed(self):
        p = load('portfolio-run')
        with patch.object(p.fc, 'psql', return_value='100'):
            self.assertEqual(p.phase_bill_batch()['result'], 'FAIL')

if __name__ == '__main__':
    unittest.main(verbosity=2)
