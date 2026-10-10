import unittest
from application.conversation_memory.report import summarize


class ReportTests(unittest.TestCase):
    def test_both_calls_counted_and_unknown_propagates(self):
        report = summarize([{'case_id': 'x', 'strategy': 'memory', 'usage': {'input_tokens': 30, 'output_tokens': 5}},
                            {'case_id': 'x', 'strategy': 'fixed', 'usage': {'input_tokens': 20, 'output_tokens': 4}}])
        self.assertEqual(report['memory']['input_tokens'], 30)
        self.assertEqual(report['paired_cases'], ['x'])
        self.assertIsNone(report['memory']['cost'])

    def test_failure_excludes_both_sides_from_paired_totals(self):
        report = summarize([{'case_id': 'x', 'strategy': 'memory', 'error': 'timeout'},
                            {'case_id': 'x', 'strategy': 'fixed', 'usage': {'input_tokens': 20, 'output_tokens': 4}}])
        self.assertEqual(report['paired_cases'], [])
        self.assertEqual(report['failed_cases'], ['x'])
