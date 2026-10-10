import json
import tempfile
import unittest
from pathlib import Path
from application.evaluation.budget import reserve_request


class BudgetTests(unittest.TestCase):
    def test_reservation_survives_failures_and_rejects_overspend(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'budget.json'
            path.write_text(json.dumps({'limit_cny': '0.04', 'reserved_cny': '0', 'requests': 0}))
            body = {'model': 'qwen3.7-plus', 'max_tokens': 2048, 'enable_thinking': False,
                    'messages': [{'role': 'user', 'content': '你好'}]}
            reserve_request(path, body)
            with self.assertRaises(ValueError):
                reserve_request(path, body)
            self.assertEqual(json.loads(path.read_text())['requests'], 1)

    def test_rejects_unbounded_or_changed_model(self):
        for body in ({'model': 'another'}, {'model': 'qwen3.7-plus', 'max_tokens': 9000},
                     {'model': 'qwen3.7-plus', 'max_tokens': 2048, 'enable_thinking': True}):
            with self.assertRaises(ValueError):
                reserve_request(Path('/nonexistent'), body)

    def test_sanitized_tool_result_keeps_fields_required_for_completion(self):
        from application.evaluation.sanitize import sanitize_result
        from application.evaluation.scoring import score_case
        case = {'tool_expectation': {'outcome': 'success', 'tracking_id': 'DEV001', 'status': '已揽收'}}
        result = sanitize_result({'status': 'success', 'tool_events': [case['tool_expectation']]})
        self.assertTrue(score_case(case, result)['tool_complete'])
