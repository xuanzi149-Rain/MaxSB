import unittest
from application.model_routing.config import parse_policy
from application.model_routing.policy import select_route
from application.model_routing.validation import validate_output

LOW = '00000000-0000-0000-0000-000000000001'
HIGH = '00000000-0000-0000-0000-000000000002'

def config(**kwargs):
    return {'enabled': True, 'low': {'model_id': LOW, 'params': {}},
            'high': {'model_id': HIGH, 'params': {}},
            'contract': {'required_fields': ['name']}, **kwargs}

class RoutingTests(unittest.TestCase):
    def test_config_disabled_and_invalid(self):
        self.assertFalse(parse_policy({}).enabled)
        for bad in [config(high={'model_id': LOW}), config(timeout=True), config(timeout=121),
                    config(extra=1), config(low={'model_id': LOW, 'params': {'max_tokens': -1}}),
                    config(low={'model_id': LOW, 'params': {'temperature': 3}}),
                    config(low={'model_id': LOW, 'params': {'max_tokens': 2.5}}), config(contract={'required_fields': ['x'] * 65}),
                    config(low={'model_id': LOW, 'params': {'api_key': 'secret'}})]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_policy(bad)

    def test_rules_conservative(self):
        p = parse_policy(config())
        for question, role in [('提取姓名', 'low'), ('分类这段文本', 'low'), ('比较两段资料并提取姓名', 'high'),
                               ('提取姓名并解释原因', 'high'), ('提取姓名，翻译成英文', 'high'),
                               ('Extract names, summarize the document', 'high'),
                               ('分类客户需求，制定营销方案', 'high'), ('继续', 'high'), ('你好', 'high')]:
            with self.subTest(question=question):
                self.assertEqual(select_route(question, p, has_history=False, has_tool_results=False).role, role)
        self.assertEqual(select_route('提取姓名', p, has_history=True, has_tool_results=False).role, 'high')
        self.assertEqual(select_route('提取姓名', p, has_history=False, has_tool_results=True).role, 'high')
        self.assertEqual(select_route('提取姓名', parse_policy(config(contract={})),
                                      has_history=False, has_tool_results=False).role, 'high')

    def test_strict_json_and_citations(self):
        contract = parse_policy(config(contract={'required_fields': ['name'], 'citation_field': 'refs',
                                                 'evidence_reference': ['search', 'paragraph_list']})).contract
        self.assertEqual(validate_output('{"name":"A","refs":["p1"]}', contract, frozenset({'p1'})), [])
        for raw in ['{"name":NaN,"refs":[]}', '{"name":1,"name":2,"refs":[]}', '[]',
                    '{"refs":[]}', '{"name":"A","refs":["fake"]}', '{"name":"A","refs":"p1"}',
                    '```json\n{}\n```']:
            with self.subTest(raw=raw):
                self.assertTrue(validate_output(raw, contract, frozenset({'p1'})))
        self.assertEqual(validate_output('{"name":"A","refs":[]}', contract, frozenset()), [])

    def test_overflow_number_rejected(self):
        contract = parse_policy(config()).contract
        self.assertTrue(validate_output('{"name":1e9999}', contract, frozenset()))
