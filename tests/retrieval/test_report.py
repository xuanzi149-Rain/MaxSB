import importlib
import unittest


class ReportTests(unittest.TestCase):
    def setUp(self):
        try:
            self.summarize = importlib.import_module('application.retrieval.report').summarize_pairs
        except ImportError:
            self.fail('Grouped retrieval report is not implemented')

    def row(self, **changes):
        return {**{'case_id': 'c1', 'category': 'complex', 'enabled': True, 'status': 'success',
                   'input_tokens': None, 'output_tokens': None, 'actual_cost': None,
                   'score': {'correct': None, 'citation_accuracy': None, 'evidence_recall': .5,
                             'missing_evidence_ids': ['required-end']},
                   'turns': [{'retrieval_ms': 12}]}, **changes}

    def test_missing_measurements_are_unknown_not_zero(self):
        group = self.summarize([self.row()])['complex']['dynamic']
        self.assertIsNone(group['correctness'])
        self.assertIsNone(group['input_tokens'])
        self.assertEqual(group['input_tokens_coverage'], 0)
        self.assertIsNone(group['actual_cost'])
        self.assertEqual(group['evidence_recall'], .5)
        self.assertEqual(group['retrieval_ms'], 12)

    def test_complex_missing_evidence_is_explicit_failure(self):
        group = self.summarize([self.row()])['complex']['dynamic']
        self.assertEqual(group['quality_failures'], ['c1'])
        self.assertEqual(group['missing_evidence'], {'c1': ['required-end']})

    def test_grouping_does_not_hide_complex_loss_in_simple_success(self):
        rows = [self.row(), self.row(case_id='c2', category='simple', input_tokens=0,
                                     score={'correct': True, 'evidence_recall': 1, 'citation_accuracy': 1}),
                self.row(enabled=False, input_tokens=100)]
        report = self.summarize(rows)
        self.assertEqual(report['simple']['dynamic']['correctness'], 1)
        self.assertEqual(report['simple']['dynamic']['input_tokens'], 0)
        self.assertEqual(report['complex']['fixed']['input_tokens'], 100)
        self.assertEqual(report['complex']['dynamic']['quality_failures'], ['c1'])
        self.assertEqual(report['none']['dynamic']['count'], 0)
        self.assertIsNone(report['none']['dynamic']['evidence_recall'])

    def test_failed_partial_run_tokens_not_misreported_as_complete(self):
        group = self.summarize([self.row(status='failed', input_tokens=5)])['complex']['dynamic']
        self.assertEqual(group['execution_failures'], ['c1'])
        self.assertEqual(group['success_count'], 0)

    def test_dataset_scenario_exposes_complex_cases_misclassified_as_simple(self):
        row = self.row(category='simple', scenario='multi_evidence')
        report = self.summarize([row], group_by='scenario')
        self.assertEqual(report['multi_evidence']['dynamic']['quality_failures'], ['c1'])
        self.assertNotIn('simple', report)
