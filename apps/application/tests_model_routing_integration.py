# coding=utf-8
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4
from django.test import TestCase
from models_provider.models import Model
from application.model_routing.integration import validate_definition, resolve_evidence
from application.model_routing.config import parse_policy
from application.tests_model_routing_runtime import POLICY, LOW, HIGH

from application.tests_tool_recovery_store import RecoveryFixture
from application.tests_tool_recovery_runtime import graph
from application.flow.common import Workflow
from application.flow.workflow_manage import WorkflowManage
from application.tool_recovery.runtime import RecoveryRuntime
from application.models import ApplicationVersion, ToolRun
from langchain_core.messages import AIMessageChunk

class RoutingIntegrationTests(TestCase):
    def setUp(self):
        for identity in (LOW, HIGH):
            Model.objects.create(id=identity, name=identity, workspace_id='default', model_type='LLM',
                                 model_name='test', provider='test', credential='', status='SUCCESS')
        self.definition = {'nodes': [{'id': 'ai', 'type': 'ai-chat-node',
            'properties': {'node_data': {'model_routing': POLICY}}}], 'edges': []}

    def test_permission_and_status_revalidated_without_model_call(self):
        validate_definition(self.definition, 'default')
        for changes in ({'workspace_id': 'other'}, {'status': 'ERROR'}, {'model_type': 'EMBEDDING'}):
            Model.objects.filter(id=LOW).update(**changes)
            with self.assertRaises(ValueError):
                validate_definition(self.definition, 'default')
            Model.objects.filter(id=LOW).update(workspace_id='default', status='SUCCESS', model_type='LLM')
        Model.objects.filter(id=LOW).delete()
        with self.assertRaises(ValueError):
            validate_definition(self.definition, 'default')

    def test_evidence_id_and_content_come_from_same_bound_result(self):
        policy = parse_policy({**POLICY, 'contract': {'citation_field': 'refs',
                                                    'evidence_reference': ['s', 'paragraph_list']}})
        node = NS(workflow_manage=NS(flow=NS(nodes=[NS(id='s', type='search-dataset-node')]),
                  get_reference_field=lambda *args: [{'id': 'p1', 'content': 'true evidence'}]))
        text, ids = resolve_evidence(node, policy)
        self.assertEqual(ids, frozenset({'p1'}))
        self.assertIn('true evidence', text)
        node.workflow_manage.flow.nodes[0].type = 'tool-node'
        with self.assertRaises(ValueError):
            resolve_evidence(node, policy)




class RoutingRecoveryTests(RecoveryFixture):
    def test_completed_routed_ai_is_restored_without_another_model_call(self):
        definition = graph()
        definition['nodes'][2]['type'] = 'ai-chat-node'
        definition['nodes'][2]['properties']['node_data'] = {
            'model_id': '', 'model_routing': POLICY, 'system': 'Answer briefly', 'prompt': 'hello',
            'dialogue_number': 0, 'is_result': True, 'model_params_setting': {}}
        version = ApplicationVersion.objects.create(application=self.app, name='ai', work_flow=definition)
        params = {'chat_id': str(self.chat.id), 'chat_record_id': str(uuid4()), 'question': '提取姓名',
                  'application_id': str(self.app.id), 'workspace_id': 'default', 'chat_user_id': 'owner',
                  'chat_user_type': 'CHAT_USER', 'stream': False, 'history_chat_record': [],
                  're_chat': False, 'debug': False}
        handler = NS(chat_info=NS(application=version, get_chat_variable=lambda: {}))
        first = WorkflowManage(Workflow.new_instance(definition), params, handler)
        first.recovery = RecoveryRuntime(first)
        async def timeout(*args):
            raise TimeoutError()
        async def success(*args):
            return NS(isError=False, content=[NS(text='tool done')])
        calls = []
        class ControlledModel:
            async def astream(self, messages, **kwargs):
                calls.append(messages)
                yield AIMessageChunk(content='bad' if len(calls) == 1 else '{"name":"A"}',
                    usage_metadata={'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12})
        with patch('application.model_routing.integration.prepare_models',
                   return_value={'low': ControlledModel(), 'high': ControlledModel()}):
            with patch('application.flow.backend.sandbox_mcp.SandboxMCPBackend.call_tool', timeout):
                first.run_chain_manage(None, None)
            run = ToolRun.objects.get(record_id=params['chat_record_id'])
            self.assertEqual(run.failed_node, 'b')
            self.assertEqual(len(calls), 2)
            claim = self.store.claim(self.identity, run.id, str(uuid4()), run.version)
            resumed = WorkflowManage(Workflow.new_instance(definition), params, handler)
            resumed.recovery = RecoveryRuntime(resumed, claim)
            with patch('application.flow.backend.sandbox_mcp.SandboxMCPBackend.call_tool', success):
                resumed.run_chain_manage(None, None)
            self.assertEqual(len(calls), 2)
            self.assertEqual(resumed.node_context[1].answer_text, '{"name":"A"}')
            self.assertEqual(len(resumed.get_answer_text_list()), 1)
        first.recovery.close()
        resumed.recovery.close()


class RoutingPersistenceTests(RecoveryFixture):
    def test_post_handler_persists_unknown_usage(self):
        from application.flow.i_step_node import WorkFlowPostHandler
        from application.models import ChatRecord
        identity = uuid4()
        details = {'ai': {'model_routing': {'attempts': [{}]}, 'message_tokens': None, 'answer_tokens': 4}}
        info = NS(ip_address='', source={}, debug=True, append_chat_record=lambda record: record.save(),
                  set_cache=lambda: None)
        workflow = NS(get_body=lambda: {'question': 'test', 'chat_record_id': identity, 'chat_id': self.chat.id},
                      get_runtime_details=lambda: details, get_answer_text_list=lambda: [],
                      chat_record=None, context={})
        with patch('application.flow.i_step_node.extract_long_term_memory.apply_async'):
            WorkFlowPostHandler(info).handler(workflow)
        record = ChatRecord.objects.get(id=identity)
        self.assertIsNone(record.message_tokens)
        self.assertEqual(record.answer_tokens, 4)

    def test_tool_workflow_ancestor_forces_high(self):
        from application.model_routing.integration import has_upstream_tools
        node = NS(node=NS(id='ai'), workflow_manage=NS(flow=NS(
            nodes=[NS(id='tool', type='tool-workflow-lib-node'), NS(id='ai', type='ai-chat-node')],
            edges=[NS(sourceNodeId='tool', targetNodeId='ai')])))
        self.assertTrue(has_upstream_tools(node))
