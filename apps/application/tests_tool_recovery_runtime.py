# coding=utf-8
from types import SimpleNamespace as NS
from uuid import uuid4
from unittest.mock import patch
from application.tests_tool_recovery_store import RecoveryFixture
from application.models import ApplicationVersion, ToolRun
from application.flow.common import Workflow
from application.flow.workflow_manage import WorkflowManage
from application.tool_recovery.runtime import RecoveryRuntime


def graph():
    def node(id, type, data):
        return {'id': id, 'type': type, 'x': 0, 'y': 0,
                'properties': {'stepName': id, 'node_data': data, 'config': {'fields': [], 'globalFields': []}}}
    mcp = {'mcp_servers': '{"s":{"url":"http://localhost:9999/mcp","transport":"streamable_http"}}',
           'mcp_source': 'custom', 'mcp_tool_id': '', 'mcp_server': 's', 'mcp_tool': 'read', 'tool_params': {},
           'recovery_policy': {'mode': 'read_only', 'retries': 0}}
    return {'nodes': [node('base-node', 'base-node', {}), node('start-node', 'start-node', {'tool_recovery': True}),
                      node('a', 'mcp-node', mcp), node('b', 'mcp-node', mcp)],
            'edges': [{'id': 'e1', 'type': 'edge', 'sourceNodeId': 'start-node', 'targetNodeId': 'a', 'sourceAnchorId': 'start-node_right'},
                      {'id': 'e2', 'type': 'edge', 'sourceNodeId': 'a', 'targetNodeId': 'b', 'sourceAnchorId': 'a_right'}]}


class RuntimeTests(RecoveryFixture):
    def test_completed_nodes_skipped_when_resuming_real_engine(self):
        definition = graph()
        version = ApplicationVersion.objects.create(application=self.app, name='recovery', work_flow=definition)
        info = NS(application=version, get_chat_variable=lambda: {})
        handler = NS(chat_info=info)
        params = {'chat_id': str(self.chat.id), 'chat_record_id': str(uuid4()), 'question': 'test',
                  'application_id': str(self.app.id), 'workspace_id': 'default', 'chat_user_id': 'owner',
                  'chat_user_type': 'CHAT_USER', 'stream': False, 'history_chat_record': [], 're_chat': False, 'debug': False}
        manager = WorkflowManage(Workflow.new_instance(definition), params, handler)
        manager.recovery = RecoveryRuntime(manager)
        calls = []
        async def call(backend, server, tool, arguments):
            calls.append(1)
            if len(calls) == 2:
                raise TimeoutError()
            return NS(isError=False, content=[NS(text='done')])
        with patch('application.flow.backend.sandbox_mcp.SandboxMCPBackend.call_tool', call):
            manager.run_chain_manage(None, None)
            run = ToolRun.objects.get(record_id=params['chat_record_id'])
            self.assertEqual(run.status, 'failed')
            self.assertEqual(calls, [1, 1])
            claim = self.store.claim(self.identity, run.id, str(uuid4()), run.version)
            resumed = WorkflowManage(Workflow.new_instance(definition), params, handler)
            resumed.recovery = RecoveryRuntime(resumed, claim=claim)
            resumed.run_chain_manage(None, None)
            self.assertEqual(calls, [1, 1, 1])
            self.assertEqual(resumed.node_context[-1].context['result'], ['done'])
        manager.recovery.close()
        resumed.recovery.close()

    def test_workflow_version_change_rejected_before_restore(self):
        from application.tool_recovery.types import RecoveryConflict
        definition = graph()
        version = ApplicationVersion.objects.create(application=self.app, name='v1', work_flow=definition)
        params = {'chat_id': str(self.chat.id), 'chat_record_id': str(uuid4()), 'question': 'test',
                  'application_id': str(self.app.id), 'workspace_id': 'default', 'chat_user_id': 'owner',
                  'chat_user_type': 'CHAT_USER', 'stream': False, 'history_chat_record': [],
                  're_chat': False, 'debug': False}
        handler = NS(chat_info=NS(application=version))
        manager = WorkflowManage(Workflow.new_instance(definition), params, handler)
        runtime = RecoveryRuntime(manager)
        ApplicationVersion.objects.create(application=self.app, name='v2', work_flow=definition)
        with self.assertRaises(RecoveryConflict):
            RecoveryRuntime(manager, runtime.claim)
        runtime.close()

    def test_completed_ai_is_restored_without_another_model_call(self):
        from langchain_core.messages import AIMessage
        definition = graph()
        definition['nodes'][2]['type'] = 'ai-chat-node'
        definition['nodes'][2]['properties']['node_data'] = {
            'model_id': 'controlled-model', 'system': 'Answer briefly', 'prompt': 'hello',
            'dialogue_number': 0, 'is_result': True, 'model_params_setting': {}}
        version = ApplicationVersion.objects.create(application=self.app, name='ai', work_flow=definition)
        params = {'chat_id': str(self.chat.id), 'chat_record_id': str(uuid4()), 'question': 'test',
                  'application_id': str(self.app.id), 'workspace_id': 'default', 'chat_user_id': 'owner',
                  'chat_user_type': 'CHAT_USER', 'stream': False, 'history_chat_record': [],
                  're_chat': False, 'debug': False}
        handler = NS(chat_info=NS(application=version, get_chat_variable=lambda: {}))
        first = WorkflowManage(Workflow.new_instance(definition), params, handler)
        first.recovery = RecoveryRuntime(first)
        path = 'application.flow.step_node.ai_chat_step_node.impl.base_chat_node'
        async def timeout(*args):
            raise TimeoutError()
        async def success(*args):
            return NS(isError=False, content=[NS(text='tool done')])
        with patch(path + '.get_model_instance_by_model_workspace_id') as model:
            model.return_value.invoke.return_value = AIMessage('only one answer')
            model.return_value.get_num_tokens_from_messages.return_value = 4
            model.return_value.get_num_tokens.return_value = 3
            with patch('application.flow.backend.sandbox_mcp.SandboxMCPBackend.call_tool', timeout):
                first.run_chain_manage(None, None)
            run = ToolRun.objects.get(record_id=params['chat_record_id'])
            self.assertEqual(run.failed_node, 'b')
            self.assertEqual(model.return_value.invoke.call_count, 1)
            claim = self.store.claim(self.identity, run.id, str(uuid4()), run.version)
            resumed = WorkflowManage(Workflow.new_instance(definition), params, handler)
            resumed.recovery = RecoveryRuntime(resumed, claim)
            with patch('application.flow.backend.sandbox_mcp.SandboxMCPBackend.call_tool', success):
                resumed.run_chain_manage(None, None)
            self.assertEqual(model.return_value.invoke.call_count, 1)
            self.assertEqual(resumed.node_context[1].answer_text, 'only one answer')
            self.assertEqual(len(resumed.get_answer_text_list()), 1)
        first.recovery.close()
        resumed.recovery.close()

    def test_write_checkpoint_failure_requires_confirmation(self):
        definition = graph()
        definition['nodes'][2]['properties']['node_data']['recovery_policy'] = {'mode': 'unprotected_write'}
        version = ApplicationVersion.objects.create(application=self.app, name='write', work_flow=definition)
        params = {'chat_id': str(self.chat.id), 'chat_record_id': str(uuid4()), 'question': 'test',
                  'application_id': str(self.app.id), 'workspace_id': 'default', 'chat_user_id': 'owner',
                  'chat_user_type': 'CHAT_USER', 'stream': False, 'history_chat_record': [],
                  're_chat': False, 'debug': False}
        manager = WorkflowManage(Workflow.new_instance(definition), params,
                                 NS(chat_info=NS(application=version, get_chat_variable=lambda: {})))
        manager.recovery = RecoveryRuntime(manager)
        calls = []
        async def call(*args):
            calls.append(1)
            return NS(isError=False, content=[NS(text='receipt')])
        checkpoint = manager.recovery.store.checkpoint
        def fail_after_write(claim, node_id, *args):
            if node_id == 'a':
                raise ValueError('size limit after remote success')
            return checkpoint(claim, node_id, *args)
        with patch('application.flow.backend.sandbox_mcp.SandboxMCPBackend.call_tool', call), \
                patch.object(manager.recovery.store, 'checkpoint', side_effect=fail_after_write):
            manager.run_chain_manage(None, None)
        run = ToolRun.objects.get(record_id=params['chat_record_id'])
        self.assertEqual(run.status, 'outcome_unknown')
        self.assertEqual(run.steps.get(node_id='a').error_type, 'checkpoint')
        self.assertEqual(calls, [1])
        manager.recovery.close()
