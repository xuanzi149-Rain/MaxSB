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
