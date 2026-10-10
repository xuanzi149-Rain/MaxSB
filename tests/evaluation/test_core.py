import copy
import importlib
import json
import unittest


class EvaluationTests(unittest.TestCase):
    def module(self, name):
        try:
            return importlib.import_module('application.evaluation.' + name)
        except ModuleNotFoundError:
            self.fail('Missing evaluation implementation: ' + name)

    def test_dataset_rejects_duplicate_ids_unknown_evidence_and_empty_turns(self):
        validate = self.module('dataset').validate_dataset
        case = dict(case_id='a', scenario='direct', turns=['question'], required_evidence_ids=['e1'],
                    expected_facts=['fact'], acceptable_answers=['fact'], tool_expectation=None,
                    rubric={'correct': 'contains all facts', 'failure': 'contradiction'})
        corpus = {'documents': [{'evidence_id': 'e1', 'text': 'fact', 'source': 'synthetic'}]}
        dataset = {'version': 'v1', 'split': 'dev', 'cases': [case]}
        validate(dataset, corpus)
        for field, value in [('turns', []), ('required_evidence_ids', ['missing']), ('expected_facts', [])]:
            invalid = copy.deepcopy(dataset)
            invalid['cases'][0][field] = value
            with self.assertRaises(ValueError):
                validate(invalid, corpus)
        with self.assertRaises(ValueError):
            validate({**dataset, 'cases': [case, case]}, corpus)

    def test_stream_handles_utf8_fragmentation_and_cumulative_usage(self):
        aggregate = self.module('stream').aggregate_stream
        frames = [{'content': '你好', 'is_end': False, 'usage': {'prompt_tokens': 5, 'completion_tokens': 1}},
                  {'content': '世界', 'is_end': True, 'usage': {'prompt_tokens': 5, 'completion_tokens': 3}}]
        data = ''.join('data: ' + json.dumps(f, ensure_ascii=False) + '\r\n\r\n' for f in frames).encode()
        result = aggregate([data[i:i + 1] for i in range(len(data))])
        self.assertEqual(result['answer'], '你好世界')
        self.assertEqual(result['input_tokens'], 5)
        self.assertEqual(result['output_tokens'], 3)
        self.assertTrue(result['complete'])

    def test_stream_missing_end_and_zero_usage_remain_unknown(self):
        aggregate = self.module('stream').aggregate_stream
        result = aggregate(['data: {"content":"partial","is_end":false}\n\n'])
        self.assertFalse(result['complete'])
        self.assertIsNone(result['input_tokens'])
        result = aggregate(['data: {"content":"","is_end":true,"usage":{"prompt_tokens":0,"completion_tokens":0}}\n\n'])
        self.assertIsNone(result['input_tokens'])

    def test_metrics_include_failed_cost_and_do_not_invent_unknowns(self):
        summarize = self.module('metrics').summarize
        rows = [dict(review={'correct': True, 'reviewer': 'alice'}, status='success', actual_cost='2',
                     currency='CNY', input_tokens=10, output_tokens=2, elapsed_seconds=1),
                dict(review={'correct': False, 'reviewer': 'alice'}, status='failed', actual_cost='1',
                     currency='CNY', input_tokens=None, output_tokens=None, elapsed_seconds=2)]
        result = summarize(rows)
        self.assertEqual(result['cost_per_success'], 3)
        self.assertEqual(result['accuracy'], .5)
        self.assertEqual(result['input_token_coverage'], .5)
        rows[1]['actual_cost'] = None
        self.assertIsNone(summarize(rows)['cost_per_success'])
        rows[1]['actual_cost'] = '1'
        rows[1]['currency'] = 'USD'
        self.assertIsNone(summarize(rows)['cost_per_success'])

    def test_unreviewed_results_are_not_final_accuracy_and_p95_is_nearest_rank(self):
        summarize = self.module('metrics').summarize
        rows = [dict(status='success', elapsed_seconds=i) for i in range(1, 21)]
        result = summarize(rows)
        self.assertIsNone(result['accuracy'])
        self.assertEqual(result['review_coverage'], 0)
        self.assertEqual(result['p95_seconds'], 19)

    def test_retrieval_does_not_prove_citation_or_semantic_correctness(self):
        score = self.module('scoring').score_case
        result = score({'required_evidence_ids': ['e1', 'e2'], 'expected_facts': ['fact'],
                        'tool_expectation': None}, {'answer': 'fact', 'retrieved_evidence_ids': ['e1']})
        self.assertEqual(result['evidence_recall'], .5)
        self.assertIsNone(result['correct'])
        self.assertIsNone(result['citation_accuracy'])

    def test_sanitize_drops_unknown_tool_params_and_credentials(self):
        sanitize = self.module('sanitize').sanitize_result
        result = sanitize({'answer': 'public', 'api_key': 'secret', 'trace': [
            {'node_id': 'n', 'status': 200, 'credential': {'token': 'secret'}, 'tool_params': {'x': 'secret'}}]})
        self.assertNotIn('secret', json.dumps(result))
        self.assertEqual(result['trace'][0]['node_id'], 'n')

    def test_comparison_joins_ids_and_flags_dataset_changes(self):
        compare = self.module('compare').compare_runs
        left = {'dataset_hash': 'a', 'config_hash': 'x', 'cases': [{'case_id': 'a', 'answer': '1'}]}
        right = {'dataset_hash': 'b', 'config_hash': 'x', 'cases': [{'case_id': 'b', 'answer': '2'}]}
        result = compare(left, right)
        self.assertFalse(result['comparable'])
        self.assertEqual(len(result['cases']), 2)
        self.assertTrue(all(row['unmatched'] for row in result['cases']))
