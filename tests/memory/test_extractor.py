import unittest
from application.conversation_memory.extractor import parse_operations
from application.conversation_memory.types import MemorySnapshot


class ExtractorTests(unittest.TestCase):
    def test_invalid_json_rejected(self):
        self.assertEqual(parse_operations('not json', '预算3000', MemorySnapshot(), 'turn').status, 'invalid')

    def test_fabricated_quote_rejected(self):
        text = '{"operations":[{"action":"add","entity":"旅行","attribute":"预算","value":"4000","quote":"预算4000"}]}'
        self.assertEqual(parse_operations(text, '预算3000', MemorySnapshot(), 'turn').status, 'invalid')

    def test_explicit_value_and_quote(self):
        text = '{"operations":[{"action":"add","entity":"旅行","attribute":"预算","value":"3000","quote":"预算3000"}]}'
        result = parse_operations(text, '预算3000', MemorySnapshot(), 'turn')
        self.assertEqual(result.operations[0].value, '3000')
        self.assertEqual(result.operations[0].source, 'turn')

    def test_model_cannot_claim_explicit_authority(self):
        text = '{"operations":[{"action":"add","entity":"旅行","attribute":"预算","value":"3000","quote":"预算3000","explicit":true}]}'
        self.assertEqual(parse_operations(text, '预算3000', MemorySnapshot(), 'turn').status, 'invalid')

    def test_hypothetical_correction_pending(self):
        from application.conversation_memory.policy import apply_operations
        from application.conversation_memory.types import Operation
        state = apply_operations(MemorySnapshot(), [Operation('add', entity='旅行', attribute='预算',
                                 value='3000', quote='预算3000')]).snapshot
        import json
        text = json.dumps({'operations': [{'action': 'replace', 'target': state.facts[0]['id'],
                          'value': '4000', 'quote': '如果预算改为4000呢？'}]})
        result = parse_operations(text, '如果预算改为4000呢？', state, 'turn')
        self.assertFalse(result.operations[0].explicit)

    def test_unique_ordinal_has_real_historical_source(self):
        import json
        text = json.dumps({'operations': [{'action': 'add', 'entity': '当前任务', 'attribute': '选择',
                          'value': 'Beta', 'quote': '选择第二款'}]})
        result = parse_operations(text, '选择第二款', MemorySnapshot(), 'turn',
                                  evidence=[{'id': 'old', 'question': '两款相机', 'answer': '1. Alpha\n2. Beta'}])
        self.assertEqual(result.operations[0].action, 'add')
        self.assertEqual(result.operations[0].value, 'Beta')

    def test_optional_null_target_on_add(self):
        text = '{"operations":[{"action":"add","entity":"当前任务","attribute":"旅行预算","value":"3000元","target":null,"quote":"我的旅行预算是3000元"}]}'
        result = parse_operations(text, '我的旅行预算是3000元，请记住。', MemorySnapshot(), 'turn')
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.operations[0].target, '')

    def test_wrong_entity_target_cannot_replace_confirmed_fact(self):
        import json
        from application.conversation_memory.types import Operation
        from application.conversation_memory.policy import apply_operations
        state = apply_operations(MemorySnapshot(), [Operation('add', entity='相机', attribute='预算', value='3000'),
                              Operation('add', entity='电脑', attribute='预算', value='8000')]).snapshot
        text = json.dumps({'operations': [{'action': 'replace', 'target': state.facts[0]['id'],
                          'value': '9000', 'quote': '电脑预算改为9000'}]})
        result = parse_operations(text, '电脑预算改为9000', state, 'turn')
        self.assertEqual(result.status, 'invalid')

    def test_hypothetical_add_not_confirmed(self):
        text = '{"operations":[{"action":"add","entity":"当前任务","attribute":"预算","value":"3000","quote":"如果预算3000呢？"}]}'
        result = parse_operations(text, '如果预算3000呢？', MemorySnapshot(), 'turn')
        self.assertEqual(result.operations[0].action, 'pending')

    def test_quoted_example_not_confirmed(self):
        text = '{"operations":[{"action":"add","entity":"当前任务","attribute":"预算","value":"3000","quote":"预算3000"}]}'
        result = parse_operations(text, '例如客户说“预算3000”时怎么办', MemorySnapshot(), 'turn')
        self.assertEqual(result.operations[0].action, 'pending')
