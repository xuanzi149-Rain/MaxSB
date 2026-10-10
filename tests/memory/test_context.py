import unittest
from application.conversation_memory.context import select_context
from application.conversation_memory.policy import apply_operations
from application.conversation_memory.types import MemorySnapshot, Operation


class ContextTests(unittest.TestCase):
    def test_whole_fact_budget_and_current_question_not_modified(self):
        snapshot = apply_operations(MemorySnapshot(), [Operation('add', entity='旅行', attribute='预算',
                                   value='4000', quote='预算4000', source='turn')]).snapshot
        selected = select_context('预算是多少？', snapshot, [], len, 2048)
        self.assertIn('4000', selected.block)
        self.assertEqual(selected.facts[0]['source'], 'turn')
        short = select_context('问' * 3000, snapshot, [], len, 10)
        self.assertEqual(short.facts, [])
        self.assertEqual(short.block, '')

    def test_pending_not_presented_as_confirmed(self):
        state = apply_operations(MemorySnapshot(), [Operation('pending', entity='商品', attribute='选择',
                                 value='第二款', quote='第二款', source='turn')]).snapshot
        result = select_context('它如何', state, [], len, 2048)
        self.assertIn('pending', result.block)
        self.assertIn('澄清', result.block)

    def test_tokenizer_failure_marked(self):
        def failed(_):
            raise RuntimeError()
        result = select_context('你好', MemorySnapshot(), [{'question': '你好', 'answer': '您好'}], failed, 2048)
        self.assertEqual(result.counting, 'utf8_upper_estimate')
        self.assertEqual(len(result.history), 1)
