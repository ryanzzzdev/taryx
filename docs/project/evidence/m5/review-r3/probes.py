"""Run: python3 docs/project/evidence/m5/review-r3/probes.py.
Additional isolated checks for the round-three remediation; no service mutations.
"""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]
spec = importlib.util.spec_from_file_location('r2', Path(__file__).parents[1] / 'review-r2/probes.py')
r2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r2)

class RemediationTests(unittest.TestCase):
    def test_successful_ingest_still_passes(self):
        result = r2.GateTests().ingest('r1.nem12: published (180000 intervals, 180000 selected, 0 quarantined)')
        self.assertEqual(result['result'], 'PASS')

    def test_partial_selection_fails(self):
        result = r2.GateTests().ingest('r1.nem12: published (180000 intervals, 179999 selected, 0 quarantined)')
        self.assertEqual(result['result'], 'FAIL')

    def test_unparseable_outcome_fails(self):
        self.assertEqual(r2.GateTests().ingest('unexpected output')['result'], 'FAIL')

    def repeat(self, output, month='9'):
        p = r2.load('portfolio-run')
        with patch.dict(os.environ), patch.object(p, 'REPEAT_MONTHS', month), patch.object(p.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), patch.object(p.fc, 'api', return_value=SimpleNamespace(stdout=output)):
            return p.phase_ingest_repeats()[0]

    def test_repeat_bad_outcomes_fail(self):
        for output in ('r1.nem12: rejected (unknown_nmi)', 'r1.nem12: duplicate', 'r1.nem12: published (180000 intervals, 0 selected, 180000 quarantined)', 'r1.nem12: published (180000 intervals, 179999 selected, 0 quarantined)'):
            with self.subTest(output=output):
                self.assertEqual(self.repeat(output)['result'], 'FAIL')

    def test_repeat_positive_outcome_passes(self):
        self.assertEqual(self.repeat('r1.nem12: published (180000 intervals, 180000 selected, 0 quarantined)')['result'], 'PASS')

    def test_october_requires_31_days(self):
        self.assertEqual(self.repeat('r1.nem12: published (180000 intervals, 180000 selected, 0 quarantined)', '10')['result'], 'FAIL')
        self.assertEqual(self.repeat('r1.nem12: published (186000 intervals, 186000 selected, 0 quarantined)', '10')['result'], 'PASS')

    def test_month_lengths(self):
        for month, days in ((2,28),(4,30),(10,31)):
            with self.subTest(month=month), patch.dict(os.environ, {'R1_MONTH': str(month)}):
                m = r2.load('measure-budgets')
                self.assertEqual(len(m.R1_DAYS), days)
                self.assertEqual(m.r1_nem12().count('\n300,') * 48, days * 6000)

if __name__ == '__main__':
    unittest.main(verbosity=2)
