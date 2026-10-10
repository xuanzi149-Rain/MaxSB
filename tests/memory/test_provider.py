import unittest
from types import SimpleNamespace
from application.conversation_memory.extractor import extract_operations
from application.conversation_memory.config import DEFAULTS
from application.conversation_memory.types import MemorySnapshot


class ProviderTests(unittest.TestCase):
    def test_anthropic_bounded_extraction_and_usage(self):
        calls = []
        options = []
        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=17, output_tokens=8),
                content=[SimpleNamespace(type='text', text='{"operations":[]}')])
        def with_options(**kwargs):
            options.append(kwargs)
            return SimpleNamespace(messages=SimpleNamespace(create=create))
        model = SimpleNamespace(_client=SimpleNamespace(with_options=with_options, messages=True),
                                model='claude-fixture', get_num_tokens=len)
        result = extract_operations(model, '预算3000', MemorySnapshot(), [], DEFAULTS)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.usage['input_tokens'], 17)
        self.assertEqual(result.usage['output_tokens'], 8)
        self.assertEqual(options, [{'timeout':20, 'max_retries':0}])
        self.assertEqual(calls[0]['max_tokens'], 1024)
        self.assertEqual(calls[0]['thinking'], {'type':'disabled'})
        self.assertEqual(calls[0]['model'], 'claude-fixture')
        self.assertEqual(calls[0]['messages'][0]['role'], 'user')

    def test_unsupported_provider_explicit_and_unknown_usage(self):
        result = extract_operations(SimpleNamespace(), '预算3000', MemorySnapshot(), [], DEFAULTS)
        self.assertEqual(result.status, 'unsupported')
        self.assertIsNone(result.usage['input_tokens'])
