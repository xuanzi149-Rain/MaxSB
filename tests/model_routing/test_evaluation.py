import unittest
from application.evaluation.routing import price_attempt, compare_routing
from application.evaluation.usage import extract_usage

class EvaluationTests(unittest.TestCase):
    def test_price_and_unknown_cache(self):
        price = {'currency': 'CNY', 'version': 'test-v1', 'source': 'test fixture',
                 'valid_from': '2026-10-01T00:00:00+00:00', 'valid_until': '2026-11-01T00:00:00+00:00',
                 'input_per_million': '2', 'output_per_million': '8', 'cache_per_million': '1'}
        attempt = {'started_at': '2026-10-10T12:00:00+00:00',
                   'usage': {'input_tokens': 1000, 'output_tokens': 100, 'cache_read_tokens': 200}}
        self.assertEqual(price_attempt(attempt, price)['priced_cost'], '0.0026')
        self.assertIsNone(price_attempt({**attempt, 'usage': {'input_tokens': 1000}}, price)['priced_cost'])
        self.assertIsNone(price_attempt({**attempt, 'started_at': '2027-01-01T00:00:00+00:00'}, price)['priced_cost'])

    def test_callback_dedup_and_model_identity(self):
        run = {'id': 'one', 'run_type': 'llm', 'extra': {'metadata': {'routing_model_id': 'model'}},
               'outputs': {'llm_output': {'token_usage': {'prompt_tokens': 4, 'completion_tokens': 2}}}}
        result = extract_usage([run, run])
        self.assertEqual(result['model_call_count'], 1)
        self.assertEqual(result['model_calls'][0]['model_id'], 'model')
        self.assertEqual(result['input_tokens'], 4)

    def test_comparison_requires_reviews_and_complete_cost(self):
        row = {'case_id': 'q', 'scenario': 'simple', 'status': 'success', 'actual_cost': 1,
               'currency': 'CNY', 'elapsed_seconds': 1,
               'review': {'correct': True, 'reviewer': 'human', 'citation_total': 0, 'citation_supported': 0},
               'score': {'evidence_recall': 1}}
        groups = {k: {'dataset_hash': 'same', 'contract_hash': 'same', 'snapshot': {key: 'same' for key in
                     ('image_id', 'code_sha', 'local_diff_hash', 'evaluation_source_hash', 'routing_protocol_hash')}, 'cases': [dict(row)]}
                  for k in ('low', 'high', 'routing')}
        groups['high']['cases'][0]['actual_cost'] = 2
        self.assertTrue(compare_routing(groups, {})['cost_optimized'])
        groups['routing']['snapshot']['image_id'] = 'different'
        self.assertFalse(compare_routing(groups, {})['comparable'])
        groups['routing']['snapshot']['image_id'] = 'same'
        groups['routing']['cases'][0]['actual_cost'] = None
        self.assertFalse(compare_routing(groups, {})['cost_optimized'])
        groups['routing']['cases'][0]['review'] = {'citation_total': None, 'citation_supported': None}
        self.assertFalse(compare_routing(groups, {})['quality_passed'])

    def test_budget_atomic_limit_and_unapproved_model(self):
        import json
        import tempfile
        from pathlib import Path
        from application.evaluation.budget import reserve_routing_request
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'budget.json'
            path.write_text(json.dumps({'version': 2, 'limit_cny': '0.001', 'reserved_cny': '0', 'requests': 0,
                'models': {'low': {'endpoint': 'https://models.example/v1/chat/completions',
                                  'input_per_million': '2', 'output_per_million': '8', 'max_tokens': 100}}}))
            with self.assertRaises(ValueError):
                reserve_routing_request(str(path), 'https://models.example/v1/chat/completions',
                                        {'model': 'low', 'max_tokens': 100, 'messages': []})
            self.assertEqual(json.loads(path.read_text())['requests'], 0)
            ledger = json.loads(path.read_text())
            ledger['limit_cny'] = '100'
            path.write_text(json.dumps(ledger))
            reserve_routing_request(str(path), 'https://models.example/v1/chat/completions',
                                    {'model': 'low', 'max_tokens': 100, 'messages': []})
            self.assertEqual(json.loads(path.read_text())['requests'], 1)
            with self.assertRaises(ValueError):
                reserve_routing_request(str(path), 'https://other.example/v1/chat/completions',
                                        {'model': 'low', 'max_tokens': 100, 'messages': []})

    def test_trace_prices_every_attempt_and_keeps_bill_unknown(self):
        from application.evaluation.routing import price_trace
        price = {'currency': 'CNY', 'version': 'v1', 'source': 'fixture', 'model_name': 'low',
                 'valid_from': '2026-10-01T00:00:00+00:00', 'valid_until': '2026-11-01T00:00:00+00:00',
                 'input_per_million': '2', 'output_per_million': '8'}
        attempt = {'model_id': 'id', 'model_name': 'low', 'started_at': '2026-10-10T12:00:00+00:00',
                   'usage': {'input_tokens': 1000, 'output_tokens': 100}}
        trace = price_trace({'attempts': [dict(attempt), dict(attempt)]}, {'id': price})
        self.assertEqual(trace['priced_cost'], '0.0056')
        self.assertIsNone(trace['actual_cost'])
        trace['attempts'][1]['usage'] = {}
        self.assertIsNone(price_trace(trace, {'id': price})['priced_cost'])
