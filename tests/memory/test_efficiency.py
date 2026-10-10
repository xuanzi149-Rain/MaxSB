import json
import unittest
from types import SimpleNamespace
from application.conversation_memory.extractor import extract_operations
from application.conversation_memory.context import select_context
from application.conversation_memory.types import MemorySnapshot
from application.conversation_memory.config import DEFAULTS


class EfficiencyTests(unittest.TestCase):
    def model(self):
        calls = []
        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"operations":[]}'))])
        client = SimpleNamespace(with_options=lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create))))
        return SimpleNamespace(root_client=client, model_name='test', get_num_tokens=len), calls

    def test_exact_control_skips_paid_extraction_but_mixed_fact_does_not(self):
        for question in ['', '你好', '谢谢', '先暂停推荐，只回复好。', '请继续等待，只回复好。']:
            model, calls = self.model()
            result = extract_operations(model, question, MemorySnapshot(), [], DEFAULTS)
            self.assertEqual(calls, [], question)
            self.assertEqual(result.usage['input_tokens'], 0)
            self.assertEqual(result.status, 'ok')
        for question in ['你好，我预算3000', '先暂停推荐，预算改成5000，只回复好', '谢谢，我选择第二款']:
            model, calls = self.model()
            extract_operations(model, question, MemorySnapshot(), [], DEFAULTS)
            self.assertEqual(len(calls), 1)

    def test_extraction_omits_audit_metadata_and_unneeded_history(self):
        model, calls = self.model()
        fact = {'id':'fact', 'entity':'相机', 'attribute':'预算', 'value':'3000', 'status':'confirmed',
                'source':'secret-source-marker', 'updated_at':'old-date-marker', 'version':1}
        history = [{'id':'old','question':'讲笑话','answer':'unrelated-answer-marker'}]
        extract_operations(model, '相机预算改成4000', MemorySnapshot([fact]), history, DEFAULTS)
        text = calls[0]['messages'][1]['content']
        self.assertNotIn('secret-source-marker', text)
        self.assertNotIn('old-date-marker', text)
        self.assertNotIn('unrelated-answer-marker', text)
        self.assertIn('fact', text)
        extract_operations(model, '选择第二款', MemorySnapshot(), history, DEFAULTS)
        self.assertIn('unrelated-answer-marker', calls[1]['messages'][1]['content'])

    def test_answer_block_is_compact_but_trace_keeps_provenance(self):
        fact = {'id':'fact', 'entity':'旅行', 'attribute':'预算', 'value':'4000', 'status':'confirmed',
                'source':'source-marker', 'updated_at':'date-marker', 'version':1, 'quote':'预算改为4000'}
        result = select_context('预算多少', MemorySnapshot([fact], 1), [], len, 2048)
        self.assertNotIn('source-marker', result.block)
        self.assertNotIn('date-marker', result.block)
        self.assertIn('4000', result.block)
        self.assertEqual(result.facts[0]['source'], 'source-marker')
        self.assertLess(len(result.block), len(json.dumps(fact, ensure_ascii=False)))

    def test_multimodal_history_is_budgeted_without_flattening_messages(self):
        turns = [{'id':'old', 'question':[{'type':'text','text':'预算3000'},
                  {'type':'image_url','image_url':{'url':'https://example.invalid/image.png'}}],
                  'answer':[{'type':'text','text':'收到'}]}]
        result = select_context('继续', MemorySnapshot(), turns, len, 2048)
        self.assertEqual(result.history, turns)
        self.assertIsInstance(result.history[0]['question'], list)
