# coding=utf-8
from unittest.mock import patch
from application.tests_memory_store import MemoryFixture
from application.conversation_memory.service import prepare_memory_context, finish_usage
from application.conversation_memory.config import parse_memory_policy
from application.conversation_memory.types import ExtractionResult, Operation


class MemoryRuntimeTests(MemoryFixture):
    def prepare(self, question='预算3000', record_id=None):
        from uuid import uuid4
        from types import SimpleNamespace
        return prepare_memory_context(self.identity, str(self.chat.id), str(record_id or uuid4()), question,
                                      SimpleNamespace(get_num_tokens=len), parse_memory_policy({'enabled': True}), [])

    def test_extraction_updates_model_context(self):
        def extract(model, question, snapshot, evidence, limits, source=''):
            return ExtractionResult([Operation('add', entity='旅行', attribute='预算', value='3000',
                                    quote=question, source=source)], usage={'input_tokens': 10, 'output_tokens': 2})
        with patch('application.conversation_memory.service.extract_operations', side_effect=extract):
            selected, trace = self.prepare()
        self.assertIn('3000', selected.block)
        self.assertEqual(trace['selected_facts'][0]['source'], self.store.sources(self.identity, self.chat.id)[0]['id'].__str__())
        finish_usage(trace, {'input_tokens': 20, 'output_tokens': 3})
        self.assertEqual(trace['total_usage']['input_tokens'], 30)
        self.assertEqual(trace['total_usage']['output_tokens'], 5)

    def test_extraction_failure_does_not_inject_old_facts(self):
        ticket = self.begin()
        from application.conversation_memory.policy import apply_operations
        self.store.commit_turn(ticket, apply_operations(ticket.snapshot, [Operation('add', entity='旅行',
                               attribute='预算', value='3000', quote='预算3000', source=ticket.event_id)]))
        with patch('application.conversation_memory.service.extract_operations', return_value=ExtractionResult(status='error')):
            selected, trace = self.prepare('预算改成4000')
        self.assertEqual(selected.facts, [])
        self.assertEqual(trace['status'], 'error')
        finish_usage(trace, {'input_tokens': 20, 'output_tokens': 3})
        self.assertIsNone(trace['total_usage']['input_tokens'])

    def test_actual_ai_node_receives_memory(self):
        from contextlib import ExitStack
        from langchain_core.messages import HumanMessage, AIMessage
        from application.tests_retrieval import make_node
        from application.flow.step_node.ai_chat_step_node.impl.base_chat_node import BaseChatNode
        from application.conversation_memory.types import ContextSelection
        node = make_node(BaseChatNode)
        node.runtime_node_id = 'node'
        from types import SimpleNamespace
        node.workflow_manage.flow = SimpleNamespace(nodes=[], workflow_mode='application')
        node.workflow_manage.generate_prompt = lambda value: value
        node.workflow_manage.get_body = lambda: {'workspace_id': 'default', 'application_id': str(self.app.id),
                  'chat_user_id': 'owner', 'chat_user_type': 'CHAT_USER', 'debug': False}
        path = 'application.flow.step_node.ai_chat_step_node.impl.base_chat_node'
        with ExitStack() as stack:
            model = stack.enter_context(patch(path + '.get_model_instance_by_model_workspace_id')).return_value
            model.invoke.return_value = AIMessage('预算4000')
            stack.enter_context(patch(path + '.filter_authorized_ids', return_value=[]))
            stack.enter_context(patch.object(node, '_handle_mcp_request', return_value=None))
            stack.enter_context(patch.object(node, 'generate_prompt_question', return_value=HumanMessage('现在推荐')))
            stack.enter_context(patch('application.conversation_memory.service.prepare_memory_context',
                return_value=(ContextSelection(block='预算4000'), {'enabled': True, 'status': 'ok'})))
            node.execute('model', '按资料回答', 'prompt', 3, [], False, str(self.chat.id), str(__import__('uuid').uuid4()),
                         model_params_setting={}, memory_policy={'enabled': True}, question='现在推荐')
        messages = model.invoke.call_args.args[0]
        self.assertTrue(any('预算4000' in m.content for m in messages))
        self.assertEqual(messages[-1].content, '现在推荐')

    def test_clear_excludes_old_recent_history(self):
        from types import SimpleNamespace
        self.store.clear(self.identity, self.chat.id, 0, str(__import__('uuid').uuid4()))
        with patch('application.conversation_memory.service.extract_operations', return_value=ExtractionResult()):
            selected, _ = prepare_memory_context(self.identity, str(self.chat.id), str(__import__('uuid').uuid4()),
                '推荐一个', SimpleNamespace(get_num_tokens=len), parse_memory_policy({'enabled': True}),
                [{'id': str(__import__('uuid').uuid4()), 'question': '预算3000', 'answer': '记住了'}])
        self.assertEqual(selected.history, [])
