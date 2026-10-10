# coding=utf-8
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from django.test import SimpleTestCase
from application.tests_memory_store import MemoryFixture
from application.conversation_memory.config import DEFAULTS
from application.conversation_memory.types import ContextSelection, ExtractionResult, MemorySnapshot


class ExtendedRuntimeTests(MemoryFixture):
    def test_multimodal_and_tool_path_keep_original_message_and_raw_text(self):
        from langchain_core.messages import HumanMessage
        from application.tests_retrieval import make_node
        from application.flow.step_node.ai_chat_step_node.impl.base_chat_node import BaseChatNode
        from application.flow.common import WorkflowMode
        node = make_node(BaseChatNode)
        node.runtime_node_id = 'node'
        node.handle_variables = lambda value: value
        node.workflow_manage.get_source_type = lambda: 'APPLICATION'
        node.workflow_manage.get_source_id = lambda: str(self.app.id)
        node.workflow_manage.flow = SimpleNamespace(nodes=[], workflow_mode=WorkflowMode.APPLICATION_LOOP)
        node.workflow_manage.work_flow_post_handler = SimpleNamespace(chat_info=SimpleNamespace(application=self.app))
        node.workflow_manage.generate_prompt = lambda value: value
        node.workflow_manage.get_body = lambda: {'workspace_id':'default','application_id':str(self.app.id),
            'chat_user_id':'owner','chat_user_type':'CHAT_USER','debug':False}
        question = HumanMessage([{'type':'text','text':'用户预算3000'},
                                 {'type':'image_url','image_url':{'url':'https://example.invalid/test.png'}}])
        path = 'application.flow.step_node.ai_chat_step_node.impl.base_chat_node'
        with ExitStack() as stack:
            stack.enter_context(patch(path + '.get_model_instance_by_model_workspace_id'))
            stack.enter_context(patch(path + '.filter_authorized_ids', return_value=[]))
            stack.enter_context(patch(path + '.ToolExecutor'))
            agent = stack.enter_context(patch(path + '.mcp_response_generator', return_value=iter([])))
            stack.enter_context(patch.object(node, 'generate_prompt_question', return_value=question))
            prepare = stack.enter_context(patch('application.conversation_memory.service.prepare_memory_context',
                return_value=(ContextSelection(block='记忆预算3000'), {'enabled':True,'status':'ok'})))
            result = node.execute('model','按条件回答','prompt',3,[],True,str(self.chat.id),str(uuid4()),
                model_params_setting={},memory_policy={'enabled':True},question='用户预算3000',
                image_list=['fixture'],mcp_servers='{"fixture":{"transport":"streamable_http","url":"http://127.0.0.1:9999/mcp"}}')
        self.assertEqual(prepare.call_args.args[3], '用户预算3000')
        messages = agent.call_args.args[2]
        self.assertEqual(messages[-1].content, question.content)
        self.assertTrue(any(m.content == '记忆预算3000' for m in messages))
        self.assertEqual(result.node_variable['question'], question.content)

    def test_same_record_repeated_by_loop_extracts_once(self):
        from application.conversation_memory.service import prepare_memory_context
        model = SimpleNamespace(get_num_tokens=len)
        record_id = str(uuid4())
        with patch('application.conversation_memory.service.extract_operations', return_value=ExtractionResult()) as extract:
            args = (self.identity, str(self.chat.id), record_id, '预算3000', model, DEFAULTS, [])
            prepare_memory_context(*args)
            _, trace = prepare_memory_context(*args)
        self.assertEqual(extract.call_count, 1)
        self.assertEqual(trace['status'], 'reused')
        self.assertEqual(trace['extraction_usage']['input_tokens'], 0)


class NativeProviderProtocolTests(SimpleTestCase):
    def test_real_anthropic_sdk_local_transport(self):
        import httpx
        import anthropic
        from application.conversation_memory.extractor import extract_operations
        captured = []
        def handle(request):
            captured.append((json.loads(request.content), request.extensions['timeout']))
            return httpx.Response(200, json={'id':'msg_fixture','type':'message','role':'assistant',
                'model':'claude-fixture','content':[{'type':'text','text':'{"operations":[]}'}],
                'stop_reason':'end_turn','stop_sequence':None,'usage':{'input_tokens':17,'output_tokens':8}})
        client = anthropic.Anthropic(api_key='local-fixture-only', base_url='http://localhost',
            http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        model = SimpleNamespace(_client=client, model='claude-fixture', get_num_tokens=len)
        result = extract_operations(model, '预算3000', MemorySnapshot(), [], DEFAULTS)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.usage['input_tokens'], 17)
        self.assertEqual(captured[0][0]['max_tokens'], 1024)
        self.assertEqual(captured[0][0]['thinking'], {'type':'disabled'})
        self.assertEqual(captured[0][1]['read'], 20)
        client.close()
