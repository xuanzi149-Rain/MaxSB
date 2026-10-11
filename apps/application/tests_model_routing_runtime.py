# coding=utf-8
"""Real node boundary tests with only external model I/O replaced."""
import time
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from langchain_core.messages import AIMessageChunk
from application.tests_retrieval import make_node
from application.flow.step_node.ai_chat_step_node.impl.base_chat_node import BaseChatNode
from application.model_routing.integration import validate_node, validate_routing_workflow, routing_model_ids

LOW = '00000000-0000-0000-0000-000000000001'
HIGH = '00000000-0000-0000-0000-000000000002'
POLICY = {'enabled': True, 'low': {'model_id': LOW}, 'high': {'model_id': HIGH},
          'contract': {'required_fields': ['name']}}


class RoutingNodeTests(SimpleTestCase):
    def test_node_replaces_old_model_and_retains_failed_usage(self):
        calls = []
        class Model:
            async def astream(self, messages, **kwargs):
                calls.append(messages)
                yield AIMessageChunk(content='bad' if len(calls) == 1 else '{"name":"A"}',
                                     usage_metadata={'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12})
        for streaming in (True, False):
            calls.clear()
            node = make_node(BaseChatNode)
            node.context['start_time'] = time.time()
            node.runtime_node_id = 'ai'
            node.node.id = 'ai'
            node.node.properties['node_data'] = {'model_routing': POLICY}
            node.workflow_manage = SimpleNamespace(
                flow=SimpleNamespace(nodes=[node.node], workflow_mode='application'),
                get_body=lambda: {'workspace_id': 'default'},
                generate_prompt=lambda value: value, is_the_task_interrupted=lambda: False,
                is_result=lambda *args: True)
            with patch('application.model_routing.integration.prepare_models', return_value={'low': Model(), 'high': Model()}):
                result = node.execute('', 'system', '提取姓名', 0, [], streaming, 'chat', 'record',
                                      model_routing=POLICY, question='提取姓名')
                written = result.write_context(node, node.workflow_manage)
                if streaming:
                    list(written)
            self.assertEqual(node.context['answer'], '{"name":"A"}')
            self.assertEqual(node.context['message_tokens'], 20)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0], calls[1])
            self.assertEqual(node.get_details(0)['model_routing']['status'], 'succeeded')

    def test_invalid_combinations_and_dependencies(self):
        self.assertEqual(routing_model_ids({'model_routing': POLICY}), [LOW, HIGH])
        for field in ('tool_ids', 'mcp_servers', 'vision', 'image_list', 'application_ids'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_node({'model_routing': POLICY, field: True})
        with self.assertRaises(ValueError):
            validate_routing_workflow(SimpleNamespace(workflow_mode='application-loop', nodes=[
                {'type': 'ai-chat-node', 'properties': {'node_data': {'model_routing': POLICY}}}]))

    def test_native_sdk_stream_metadata_and_retries(self):
        import httpx
        import json
        from application.model_routing.integration import prepare_models
        from application.model_routing.executor import execute_routed
        from application.model_routing.policy import select_route
        from application.model_routing.config import parse_policy
        from models_provider.impl.base_chat_open_ai import BaseChatOpenAI
        calls = []
        async def transport(request):
            body = json.loads(request.content)
            calls.append(body)
            text = 'bad' if len(calls) == 1 else '{"name":"A"}'
            event = {'id': 'response', 'model': body['model'], 'object': 'chat.completion.chunk',
                'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': text}, 'finish_reason': None}]}
            usage = {'id': 'response', 'model': body['model'], 'object': 'chat.completion.chunk', 'choices': [],
                     'usage': {'prompt_tokens': 9, 'completion_tokens': 2, 'total_tokens': 11}}
            data = 'data: '+json.dumps(event)+'\n\ndata: '+json.dumps(usage)+'\n\ndata: [DONE]\n\n'
            return httpx.Response(200, text=data, headers={'content-type': 'text/event-stream'})
        def factory(row, **kwargs):
            kwargs['http_async_client']._transport = httpx.MockTransport(transport)
            return BaseChatOpenAI(model=row.model_name, api_key='test-only', base_url='https://local.invalid/v1',
                                 **kwargs)
        policy = parse_policy(POLICY)
        with (patch('models_provider.tools.get_model_by_id', side_effect=lambda identity, workspace:
                   SimpleNamespace(workspace_id='default', model_type='LLM', status='SUCCESS',
                                   model_name='low' if identity == LOW else 'high')),
             patch('models_provider.tools.get_model_default_params', return_value={}),
             patch('models_provider.tools.get_model', side_effect=factory)):
            models = prepare_models(policy, 'default')
            again = prepare_models(policy, 'default')
            self.assertIsNot(models['low'].http_async_client, again['low'].http_async_client)
            import asyncio
            for model in again.values():
                asyncio.run(model.root_async_client.close())
                model.root_client.close()
        trace = {}
        output = list(execute_routed([], policy, select_route('提取姓名', policy, has_history=False,
            has_tool_results=False), model_factory=models.__getitem__, evidence_ids=frozenset(),
            cancelled=lambda: False, trace=trace))
        self.assertEqual(''.join(c.content for c in output), '{"name":"A"}')
        self.assertEqual([r['model'] for r in calls], ['low', 'high'])
        self.assertTrue(all(r['stream_options']['include_usage'] for r in calls))
        self.assertEqual(trace['usage']['input_tokens'], 18)
        self.assertEqual(trace['usage']['output_tokens'], 4)
        self.assertEqual(models['low'].root_async_client.max_retries, 0)
