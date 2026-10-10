import importlib
import json
from pathlib import Path
import unittest
from application.evaluation.dataset import validate_dataset, dataset_digest
from application.evaluation.stream import aggregate_stream


class ContractTests(unittest.TestCase):
    def test_shipped_datasets_are_sealed_and_evidence_ids_exist(self):
        root = Path(__file__).resolve().parents[2] / 'docs/implementation/evaluation'
        corpus = json.loads((root / 'corpus.json').read_text())
        manifest = json.loads((root / 'manifest.json').read_text())
        self.assertEqual(dataset_digest(corpus), manifest['corpus_hash'])
        for split, count in [('dev', 20), ('frozen', 80)]:
            data = json.loads((root / f'{split}-v1.json').read_text())
            validate_dataset(data, corpus)
            self.assertEqual(len(data['cases']), count)
            self.assertEqual(dataset_digest(data), manifest['datasets'][f'{split}-v1'])
        changed = {**corpus, 'version': 'changed'}
        self.assertNotEqual(dataset_digest(changed), manifest['corpus_hash'])

    def test_node_error_is_not_a_successful_answer(self):
        result = aggregate_stream(['data: {"content":"","node_status":"ERROR","is_end":false}\n\n',
                                   'data: {"content":"","is_end":true}\n\n'])
        self.assertEqual(result['error'], 'chat_response_error')

    def test_usage_only_accepts_actual_provider_counts_and_sums_calls(self):
        try:
            extract = importlib.import_module('application.evaluation.usage').extract_usage
        except ImportError:
            self.fail('Missing provider usage extraction')
        runs = [{'run_type': 'llm', 'outputs': {'generations': [[{'message': {'kwargs': {
            'usage_metadata': {'input_tokens': 10, 'output_tokens': 3}}}}]]}, 'child_runs': []},
                {'run_type': 'llm', 'outputs': {'llm_output': {'token_usage': {'prompt_tokens': 4,
                 'completion_tokens': 2}}}, 'child_runs': []}]
        result = extract(runs)
        self.assertEqual(result['input_tokens'], 14)
        self.assertEqual(result['output_tokens'], 5)
        runs.append({'run_type': 'llm', 'outputs': {}, 'child_runs': []})
        self.assertIsNone(extract(runs)['input_tokens'])

    def test_tool_fixture_is_deterministic_and_timeout_is_observable(self):
        try:
            fixture = importlib.import_module('application.evaluation.fixtures')
        except ImportError:
            self.fail('Missing readonly tool fixture')
        scope = {}
        exec(fixture.LOOKUP_CODE, scope)
        self.assertEqual(scope['lookup']('F002')['status'], '待揽收')
        with self.assertRaises(TimeoutError):
            scope['lookup']('FT02')
        self.assertEqual(scope['lookup']('unknown')['status'], '查无记录')

    def test_tracking_id_adjacent_to_chinese_is_extracted_without_guessing(self):
        fixture = importlib.import_module('application.evaluation.fixtures')
        self.assertTrue(hasattr(fixture, 'tracking_id_from_question'))
        self.assertEqual(fixture.tracking_id_from_question('请查询DEV001，报告状态'), 'DEV001')
        with self.assertRaises(ValueError):
            fixture.tracking_id_from_question('查询F001和F002')

    def test_failed_stream_does_not_export_provider_exception_text(self):
        result = aggregate_stream(['data: {"content":"Exception: api_key=secret-value","is_end":false}\n\n'])
        self.assertNotIn('secret-value', json.dumps(result))

    def test_timeout_observation_is_not_tool_task_completion(self):
        from application.evaluation.scoring import score_case
        scored = score_case({'tool_expectation': {'outcome': 'timeout', 'tracking_id': 'FT01'}},
                            {'status': 'failed', 'tool_events': [{'outcome': 'timeout', 'tracking_id': 'FT01'}]})
        self.assertFalse(scored['tool_complete'])

    def test_incomplete_run_does_not_report_final_accuracy(self):
        from application.evaluation.metrics import summarize
        try:
            result = summarize([{'status': 'success', 'review': {'correct': True, 'reviewer': 'alice'}}], total_cases=3)
        except TypeError:
            self.fail('Missing expected batch denominator')
        self.assertIsNone(result['accuracy'])
        self.assertAlmostEqual(result['review_coverage'], 1/3)

    def test_alternative_duplicate_evidence_does_not_require_both_copies(self):
        from application.evaluation.scoring import score_case
        case = {'required_evidence_ids': ['e1', 'e2'], 'required_evidence_groups': [['e1', 'e2']]}
        self.assertEqual(score_case(case, {'retrieved_evidence_ids': ['e2']})['evidence_recall'], 1)

    def test_environment_mismatch_and_incomplete_batch_are_not_strictly_comparable(self):
        from application.evaluation.compare import compare_runs
        left = {'status': 'completed', 'dataset_hash': 'a', 'config_hash': 'b',
                'snapshot': {'image_id': 'one'}, 'cases': [], 'total': 20}
        self.assertTrue(compare_runs(left, left)['comparable'])
        self.assertFalse(compare_runs(left, {**left, 'snapshot': {'image_id': 'two'}})['comparable'])
        self.assertFalse(compare_runs(left, {**left, 'status': 'interrupted'})['comparable'])

    def test_sanitizer_erases_failed_answer_and_unstructured_error(self):
        from application.evaluation.sanitize import sanitize_result
        result = sanitize_result({'status': 'failed', 'answer': 'Authorization: Bearer secret-marker',
                                  'error': 'api_key=secret-marker'})
        self.assertNotIn('secret-marker', json.dumps(result))
