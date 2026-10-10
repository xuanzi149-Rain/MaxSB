# coding=utf-8
"""Workflow contract tests; external vector/model I/O is replaced with controlled doubles."""
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from langchain_core.documents import Document

from application.flow.step_node.search_knowledge_node.impl.base_search_knowledge_node import BaseSearchKnowledgeNode
from application.flow.step_node.reranker_node.impl.base_reranker_node import BaseRerankerNode
from application.flow.step_node.search_knowledge_node.i_search_knowledge_node import DatasetSettingSerializer
from application.retrieval.policy import decide_retrieval

SEARCH = 'application.flow.step_node.search_knowledge_node.impl.base_search_knowledge_node'
RERANK = 'application.flow.step_node.reranker_node.impl.base_reranker_node'
SETTINGS = {'top_n': 5, 'similarity': .2, 'search_mode': 'embedding', 'max_paragraph_char_number': 5000,
            'retrieval_policy': {'enabled': True}}
CONTEXT = {'enabled': True, 'token_budget': 2048, 'similarity_threshold': .95}


def make_node(cls):
    node = cls.__new__(cls)
    node.context = {}
    node.workflow_manage = SimpleNamespace(get_body=lambda: {'workspace_id': 'default'})
    node.node = SimpleNamespace(properties={'stepName': 'test'}, type=cls.type)
    node.node_params_serializer = SimpleNamespace(data={})
    node.status, node.err_message = 200, ''
    return node


def rows():
    return [{'id': str(i), 'document_id': 'doc', 'knowledge_id': 'kb', 'title': '',
             'content': content, 'similarity': .9 - i * .1, 'is_hit_handling_method': False,
             'meta': {'allow_download': False}} for i, content in enumerate(['借期21天', '借期21天', '儿童限借3本'])]


class RetrievalIntegrationTests(SimpleTestCase):
    def search(self, question, settings=None, authorized=None):
        settings = settings or SETTINGS
        node = make_node(BaseSearchKnowledgeNode)
        node.node_params_serializer = SimpleNamespace(data={'knowledge_setting': settings})
        with ExitStack() as stack:
            stack.enter_context(patch(SEARCH + '.filter_authorized_ids', return_value=(
                ['kb'] if authorized is None else authorized)))
            stack.enter_context(patch(SEARCH + '.DatabaseModelManage.get_model', return_value=None))
            stack.enter_context(patch(SEARCH + '.get_embedding_id', return_value='embedding'))
            model = stack.enter_context(patch(SEARCH + '.get_model_instance_by_model_workspace_id'))
            stack.enter_context(patch(SEARCH + '.QuerySet', return_value=MagicMock()))
            stack.enter_context(patch(SEARCH + '.connection'))
            vector = stack.enter_context(patch(SEARCH + '.VectorStore')).get_embedding_vector.return_value
            vector.query.return_value = [{'paragraph_id': '0'}, {'paragraph_id': '1'}, {'paragraph_id': '2'}]
            stack.enter_context(patch.object(node, 'list_paragraph', return_value=rows()))
            stack.enter_context(patch.object(node, 'reset_paragraph', side_effect=lambda row, _: row))
            result = node.execute(['kb'], settings, question, True, 'custom', 'knowledge', []).node_variable
        node.save_context(result, None)
        return result, node, model, vector

    def test_greeting_skips_embedding_and_vector_io_with_replayable_trace(self):
        result, node, model, vector = self.search('你好')
        self.assertEqual(result['data'], '')
        self.assertEqual(result['retrieval_budget']['status'], 'skipped')
        self.assertEqual(result['retrieved_paragraph_list'], [])
        self.assertEqual(result['is_hit_handling_method_list'], [])
        self.assertEqual(node.get_details(0)['retrieval_budget'], result['retrieval_budget'])
        model.assert_not_called()
        vector.query.assert_not_called()

    def test_query_uses_decision_before_context_processing_and_keeps_raw_sources(self):
        result, node, _, vector = self.search('借期是多少天？', {**SETTINGS, 'context_policy': CONTEXT})
        self.assertEqual(vector.query.call_args.args[7:9], (3, .2))
        self.assertEqual([p['id'] for p in result['retrieved_paragraph_list']], ['0', '1', '2'])
        self.assertEqual([p['id'] for p in result['paragraph_list']], ['0', '2'])
        self.assertEqual(result['retrieval_budget']['raw_count'], 3)
        self.assertEqual(node.context['data'], result['data'])
        self.assertGreaterEqual(result['retrieval_budget']['retrieval_ms'], 0)

    def test_empty_authorized_knowledge_skips_model_and_reports_empty_scope(self):
        result, _, model, _ = self.search('借期是多少天？', authorized=[])
        self.assertEqual(result['retrieval_budget']['status'], 'empty_scope')
        self.assertEqual(result['paragraph_list'], [])
        model.assert_not_called()

    def test_old_and_disabled_workflow_outputs_are_identical(self):
        old = {k: v for k, v in SETTINGS.items() if k != 'retrieval_policy'}
        a, _, _, _ = self.search('你好', old)
        b, _, _, _ = self.search('你好', {**old, 'retrieval_policy': {'enabled': False}})
        self.assertEqual(a, b)
        self.assertNotIn('retrieval_budget', a)

    def test_unknown_keeps_fixed_query_and_complex_expands(self):
        for question, limit in [('帮我看看', 5), ('比较成人和儿童借书条件', 8)]:
            result, _, _, vector = self.search(question)
            self.assertEqual(vector.query.call_args.args[7], limit)
            self.assertEqual(result['retrieval_budget']['top_n'], limit)

    def test_policy_serializer_roundtrip_and_range_validation(self):
        serializer = DatasetSettingSerializer(data=SETTINGS)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.data['retrieval_policy'], {'enabled': True})
        for invalid in [0, -1, 10001]:
            data = {**SETTINGS, 'retrieval_policy': {'enabled': True, 'simple': {
                'retrieve': True, 'top_n': invalid, 'rerank': False}}}
            self.assertFalse(DatasetSettingSerializer(data=data).is_valid())


class DynamicRerankerTests(SimpleTestCase):
    def execute(self, question, *, failure=False, context=True, policy=True):
        node = make_node(BaseRerankerNode)
        decision = decide_retrieval(question, SETTINGS) if policy else None
        with patch(RERANK + '.get_model_instance_by_model_workspace_id') as loader:
            if failure:
                loader.side_effect = RuntimeError('provider error with sensitive payload')
            else:
                loader.return_value.compress_documents.return_value = [
                    Document(page_content=r['content'], metadata={**r, 'relevance_score': .9}) for r in rows()]
            output = node.execute(question, {'top_n': 5, 'similarity': .2, 'max_paragraph_char_number': 5000,
                                  'context_policy': CONTEXT if context else {'enabled': False}},
                                  rows(), 'model', True, retrieval_budget=decision).node_variable
        node.save_context(output, None)
        return output, node, loader

    def test_simple_bypasses_reranker_and_still_deduplicates_original_evidence(self):
        result, node, loader = self.execute('借期是多少天？')
        loader.assert_not_called()
        self.assertEqual(result['retrieval_budget']['rerank_status'], 'skipped')
        self.assertEqual([r['metadata']['id'] for r in result['result_list']], ['0', '2'])
        self.assertEqual(node.get_details(0)['retrieval_budget'], result['retrieval_budget'])
        self.assertNotIn('relevance_score', result['result_list'][0]['metadata'])

    def test_complex_reranks_raw_candidates_before_context_deduplication(self):
        result, _, loader = self.execute('比较成人和儿童借书条件')
        sent = loader.return_value.compress_documents.call_args.args[0]
        self.assertEqual([d.metadata['id'] for d in sent], ['0', '1', '2'])
        self.assertEqual(result['retrieval_budget']['rerank_status'], 'applied')
        self.assertEqual(len(result['result_list']), 2)

    def test_unavailable_dynamic_reranker_retains_sources_without_exposing_error_payload(self):
        result, _, _ = self.execute('比较成人和儿童借书条件', failure=True)
        self.assertEqual(result['retrieval_budget']['rerank_status'], 'unavailable')
        self.assertEqual([r['metadata']['id'] for r in result['result_list']], ['0', '2'])
        self.assertNotIn('sensitive', str(result))

    def test_unlinked_and_unknown_reranker_keep_original_failure_semantics(self):
        for question, policy in [('借期是多少天？', False), ('帮我看看', True)]:
            with self.assertRaises(RuntimeError):
                self.execute(question, failure=True, policy=policy)

    def test_run_resolves_explicit_budget_and_raw_candidates_without_requiring_model_for_skip(self):
        from application.flow.step_node.reranker_node.i_reranker_node import IRerankerNode
        node = make_node(BaseRerankerNode)
        decision = decide_retrieval('借期是多少天？', SETTINGS)
        node.node_params_serializer = SimpleNamespace(data={
            'question_reference_address': ['start', 'question'],
            'reranker_reference_list': [['search', 'retrieved_paragraph_list']],
            'retrieval_budget_reference': ['search', 'retrieval_budget'],
            'reranker_model_id_type': 'custom', 'reranker_model_id': '', 'show_knowledge': True,
            'reranker_setting': {'top_n': 5, 'similarity': .2, 'max_paragraph_char_number': 5000}})
        values = {'question': '借期是多少天？', 'retrieved_paragraph_list': rows(), 'retrieval_budget': decision}
        node.workflow_manage.get_reference_field = lambda _, fields: values[fields[0]]
        result = IRerankerNode._run(node).node_variable
        self.assertEqual(result['retrieval_budget']['rerank_status'], 'skipped')
        self.assertEqual(len(result['result_list']), 3)

    def test_mismatched_source_is_rejected_instead_of_skipping_unrelated_evidence(self):
        from application.flow.step_node.reranker_node.i_reranker_node import IRerankerNode
        node = make_node(BaseRerankerNode)
        node.node_params_serializer = SimpleNamespace(data={
            'question_reference_address': ['start', 'question'],
            'reranker_reference_list': [['other', 'paragraph_list']],
            'retrieval_budget_reference': ['search', 'retrieval_budget'],
            'reranker_model_id_type': 'custom', 'reranker_model_id': 'model', 'show_knowledge': True,
            'reranker_setting': {'top_n': 5, 'similarity': .2, 'max_paragraph_char_number': 5000}})
        values = {'question': '借期是多少天？', 'paragraph_list': rows(),
                  'retrieval_budget': decide_retrieval('借期是多少天？', SETTINGS)}
        node.workflow_manage.get_reference_field = lambda _, fields: values[fields[0]]
        with self.assertRaisesMessage(ValueError, 'retrieved_paragraph_list'):
            IRerankerNode._run(node)

    def test_empty_input_does_not_load_reranker_and_replays_audit(self):
        node = make_node(BaseRerankerNode)
        with patch(RERANK + '.get_model_instance_by_model_workspace_id') as loader:
            result = node.execute('你好', {'top_n': 5}, [], '', True,
                                  retrieval_budget=decide_retrieval('你好', SETTINGS)).node_variable
        loader.assert_not_called()
        node.save_context(result, None)
        self.assertEqual(result['result_list'], [])
        self.assertEqual(node.get_details(0)['retrieval_budget']['rerank_status'], 'empty_input')

    def test_disabled_source_uses_legacy_processed_paragraphs(self):
        from application.flow.step_node.reranker_node.i_reranker_node import IRerankerNode
        node = make_node(BaseRerankerNode)
        node.node_params_serializer = SimpleNamespace(data={
            'question_reference_address': ['start', 'question'],
            'reranker_reference_list': [['search', 'retrieved_paragraph_list']],
            'retrieval_budget_reference': ['search', 'retrieval_budget'],
            'reranker_model_id_type': 'custom', 'reranker_model_id': 'model', 'show_knowledge': True,
            'reranker_setting': {'top_n': 5, 'similarity': .2, 'max_paragraph_char_number': 5000}})
        values = {'question': '借期是多少天？', 'paragraph_list': rows()[2:],
                  'retrieved_paragraph_list': rows(), 'retrieval_budget': None}
        node.workflow_manage.get_reference_field = lambda _, fields: values[fields[0]]
        with patch(RERANK + '.get_model_instance_by_model_workspace_id') as loader:
            loader.return_value.compress_documents.side_effect = lambda docs, _: [
                Document(page_content=d.page_content, metadata={**d.metadata, 'relevance_score': .9}) for d in docs]
            result = IRerankerNode._run(node).node_variable
        self.assertEqual([r['metadata']['id'] for r in result['result_list']], ['2'])
        self.assertNotIn('retrieval_budget', result)

    def test_missing_dynamic_model_falls_back_to_original_evidence(self):
        node = make_node(BaseRerankerNode)
        with patch(RERANK + '.get_model_instance_by_model_workspace_id') as loader:
            result = node.execute('比较成人和儿童借书条件',
                                  {'top_n': 5, 'similarity': .2, 'max_paragraph_char_number': 5000},
                                  rows(), '', True, retrieval_budget=decide_retrieval(
                                      '比较成人和儿童借书条件', SETTINGS)).node_variable
        loader.assert_not_called()
        self.assertEqual(result['retrieval_budget']['rerank_status'], 'unavailable')
        self.assertEqual([r['metadata']['id'] for r in result['result_list']], ['0', '1', '2'])

    def test_cleared_optional_reference_is_valid(self):
        from application.flow.step_node.reranker_node.i_reranker_node import RerankerStepNodeSerializer
        serializer = RerankerStepNodeSerializer(data={
            'reranker_setting': {'top_n': 3, 'similarity': .2, 'max_paragraph_char_number': 5000},
            'question_reference_address': ['start', 'question'],
            'reranker_reference_list': [['search', 'paragraph_list']],
            'retrieval_budget_reference': None, 'reranker_model_id': 'model', 'show_knowledge': True})
        serializer.is_valid()  # Upstream workflow serializers raise on error and return None.
        self.assertIsNone(serializer.data['retrieval_budget_reference'])


class DialogueIntegrationTests(SimpleTestCase):
    def test_ai_node_history_removes_only_current_verified_context(self):
        from application.flow.step_node.ai_chat_step_node.impl.base_chat_node import BaseChatNode
        context = '[E] 图书押金为200元，归还全部图书后退还。'
        record = MagicMock()
        record.get_node_details_runtime_node_id.return_value = {
            'question': '资料：' + context + '\n问题：押金多少？', 'answer': '200元。[E]',
            'dialogue_context': context, 'raw_question': '押金多少？'}
        messages, trace = BaseChatNode.prepare_dialogue_history(
            [record], 3, 'NODE', 'node-id', context, '归还之后如何退款？', True)
        self.assertNotIn(context, messages[0].content)
        self.assertIn('押金多少？', messages[0].content)
        self.assertEqual(messages[1].content, '200元。[E]')
        self.assertEqual(trace['removed_contexts'], 1)

    def test_workflow_history_and_disabled_node_history_remain_unchanged(self):
        from application.flow.step_node.ai_chat_step_node.impl.base_chat_node import BaseChatNode
        from langchain_core.messages import HumanMessage, AIMessage
        record = MagicMock()
        record.get_human_message.return_value = HumanMessage('预算改为900元')
        record.get_ai_message.return_value = AIMessage('已了解')
        messages, trace = BaseChatNode.prepare_dialogue_history(
            [record], 3, 'WORKFLOW', 'id', '资料', '多少钱？', True)
        self.assertEqual(messages[0].content, '预算改为900元')
        self.assertEqual(trace['removed_contexts'], 0)
        messages, _ = BaseChatNode.prepare_dialogue_history(
            [record], 0, 'WORKFLOW', 'id', '', '', True)
        self.assertEqual(messages, [])

    def test_dialogue_settings_are_optional_and_typed(self):
        from application.flow.step_node.ai_chat_step_node.i_chat_node import ChatNodeSerializer
        value = {'prompt': '回答', 'dialogue_number': 3, 'dialogue_policy_enabled': True,
                 'dialogue_context_reference': ['search', 'data']}
        serializer = ChatNodeSerializer(data=value)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertTrue(serializer.validated_data['dialogue_policy_enabled'])

    def test_live_ai_input_uses_guidance_only_when_enabled_without_tools(self):
        from application.flow.step_node.ai_chat_step_node.impl.base_chat_node import BaseChatNode
        from langchain_core.messages import HumanMessage, AIMessage
        path = 'application.flow.step_node.ai_chat_step_node.impl.base_chat_node'
        for enabled, tool_ids in [(False, []), (True, []), (True, ['tool'])]:
            node = make_node(BaseChatNode)
            node.runtime_node_id = 'node'
            node.workflow_manage.generate_prompt = lambda value: value
            with ExitStack() as stack:
                model = stack.enter_context(patch(path + '.get_model_instance_by_model_workspace_id')).return_value
                model.invoke.return_value = AIMessage('好的')
                stack.enter_context(patch(path + '.filter_authorized_ids', return_value=[]))
                stack.enter_context(patch.object(node, '_handle_mcp_request', return_value=None))
                stack.enter_context(patch.object(node, 'generate_prompt_question', return_value=HumanMessage(
                    '用户问题：请先记住前面的要求。')))
                node.execute('model', '按资料回答', 'prompt', 3, [], False, 'chat', 'record',
                             model_params_setting={}, dialogue_policy_enabled=enabled,
                             question='请先记住前面的要求。', tool_ids=tool_ids)
            messages = model.invoke.call_args.args[0]
            self.assertEqual('只用一句' in messages[0].content, enabled and not tool_ids)
            self.assertEqual(node.context['dialogue_policy']['brief_response'], enabled and not tool_ids)

    def test_clearing_dialogue_context_reference_preserves_optional_configuration(self):
        from application.flow.step_node.ai_chat_step_node.i_chat_node import ChatNodeSerializer
        serializer = ChatNodeSerializer(data={'prompt': '回答', 'dialogue_number': 3,
                                              'dialogue_context_reference': None})
        self.assertTrue(serializer.is_valid(), serializer.errors)
