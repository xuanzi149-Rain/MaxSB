import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('fault_report', Path(__file__).resolve().parents[2] /
                                             'docs/implementation/scripts/run_task5_faults.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReportTests(unittest.TestCase):
    def test_failures_stay_in_denominator_and_cost_unknown(self):
        report = module.summarize([
            {'status': 'succeeded', 'duplicates': 0, 'seconds': 1, 'cost': None},
            {'status': 'outcome_unknown', 'duplicates': 0, 'seconds': 2, 'cost': None},
        ])
        self.assertEqual(report['completion_rate'], 0.5)
        self.assertIsNone(report['extra_cost'])
        self.assertEqual(report['duplicate_side_effects'], 0)
