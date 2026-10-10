# coding=utf-8
from concurrent.futures import ThreadPoolExecutor
from django.test import SimpleTestCase
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tracers.context import collect_runs
from application.evaluation.usage import extract_usage


class ProviderUsageTests(SimpleTestCase):
    def model(self):
        return FakeMessagesListChatModel(responses=[AIMessage(content='ok', usage_metadata={
            'input_tokens': 17, 'output_tokens': 4, 'total_tokens': 21})])

    def test_real_langchain_callback_captures_provider_metadata(self):
        with collect_runs() as collector:
            self.model().invoke('fixture')
        self.assertEqual(extract_usage(collector.traced_runs)['input_tokens'], 17)
        self.assertEqual(extract_usage(collector.traced_runs)['output_tokens'], 4)

    def test_unpropagated_worker_context_reports_unknown_never_zero(self):
        with collect_runs() as collector:
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(self.model().invoke, 'fixture').result().content, 'ok')
        result = extract_usage(collector.traced_runs)
        self.assertIsNone(result['input_tokens'])
        self.assertEqual(result['usage_source'], 'unknown')

    def test_registered_budget_parameters_survive_original_model_loader(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from models_provider.tools import get_model_instance_by_model_workspace_id
        model = SimpleNamespace(model_type='LLM', model_params_form=[
            {'field': 'max_tokens', 'default_value': 2048},
            {'field': 'max_retries', 'default_value': 0},
            {'field': 'stream_usage', 'default_value': True},
            {'field': 'extra_body', 'default_value': {'enable_thinking': False}}])
        with patch('models_provider.tools.get_model_by_id', return_value=model), \
             patch('models_provider.tools.ModelManage.get_model', side_effect=lambda key, build: build(key)), \
             patch('models_provider.tools.get_model', return_value='bounded') as build:
            self.assertEqual(get_model_instance_by_model_workspace_id('fixture', 'workspace'), 'bounded')
        self.assertEqual(build.call_args.kwargs['extra_body'], {'enable_thinking': False})
        self.assertEqual(build.call_args.kwargs['max_retries'], 0)
