# coding=utf-8
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from application.chat_pipeline.I_base_chat_pipeline import ParagraphPipelineModel
from application.chat_pipeline.step.generate_human_message_step.impl.base_generate_human_message_step import (
    BaseGenerateHumanMessageStep,
)
from application.flow.step_node.reranker_node.impl.base_reranker_node import BaseRerankerNode
from application.flow.step_node.search_knowledge_node.impl.base_search_knowledge_node import BaseSearchKnowledgeNode

CONFIG = {'enabled': True, 'token_budget': 2048, 'similarity_threshold': .95}


def paragraphs():
    return [ParagraphPipelineModel.builder().add_paragraph({
        'id': str(i), 'document_id': 'doc', 'knowledge_id': 'kb', 'title': '', 'content': '同一条预约规则'
    }).add_similarity(.9).add_hit_handling_method('optimization').build() for i in range(2)]


class ContextIntegrationTests(SimpleTestCase):
    def arguments(self):
        return dict(problem_text='问题', paragraph_list=paragraphs(), history_chat_record=[], dialogue_number=0,
                    max_paragraph_char_number=5000, prompt='{data}\n{question}',
                    no_references_setting={'status': 'ai_questioning', 'value': '{question}'})

    def test_disabled_message_matches_upstream_bytes(self):
        step = BaseGenerateHumanMessageStep()
        args = self.arguments()
        expected = step.to_human_message(args['prompt'], '问题', 5000, args['paragraph_list'], {})
        self.assertEqual(step.execute(**args, context_policy={'enabled': False})[-1].content, expected.content)

    def test_enabled_pipeline_model_receives_one_copy_and_original_source(self):
        step = BaseGenerateHumanMessageStep()
        manager = SimpleNamespace(context={**self.arguments(), 'context_policy': CONFIG})
        step.valid_args(manager)
        step._run(manager)
        messages = manager.context['message_list']
        model = FakeMessagesListChatModel(responses=[AIMessage(content='ok')])
        seen = []
        from langchain_core.callbacks import BaseCallbackHandler
        class Capture(BaseCallbackHandler):
            def on_chat_model_start(self, serialized, messages, **kwargs):
                seen.extend(messages[0])
        model.invoke(messages, config={'callbacks': [Capture()]})
        self.assertEqual(seen[-1].content.count('同一条预约规则'), 1)
        self.assertEqual([p.id for p in manager.context['paragraph_list']], ['0'])
        self.assertEqual(step.get_details(manager)['context_processing']['retained_count'], 1)

    def test_budget_empty_uses_no_reference_behavior(self):
        step = BaseGenerateHumanMessageStep()
        manager = SimpleNamespace(context={**self.arguments(), 'context_policy': {**CONFIG, 'token_budget': 1}})
        step.valid_args(manager)
        step._run(manager)
        self.assertEqual(manager.context['paragraph_list'], [])
        self.assertEqual(manager.context['message_list'][-1].content, '问题')

    def test_config_survives_application_serializer_and_rejects_invalid(self):
        from application.serializers.application import KnowledgeSettingSerializer
        data = {'top_n': 5, 'similarity': .2, 'max_paragraph_char_number': 5000, 'search_mode': 'embedding',
                'no_references_setting': {'status': 'ai_questioning', 'value': '{question}'},
                'context_policy': CONFIG}
        serializer = KnowledgeSettingSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.data.get('context_policy'), CONFIG)
        serializer = KnowledgeSettingSerializer(data={**data, 'context_policy': {**CONFIG, 'token_budget': 0}})
        self.assertFalse(serializer.is_valid())

    def test_reranker_selects_before_truncation_and_preserves_metadata(self):
        node = BaseRerankerNode.__new__(BaseRerankerNode)
        node.context = {}
        node.workflow_manage = SimpleNamespace(get_body=lambda: {'workspace_id': 'default'})
        docs = [Document(page_content='同一条预约规则', metadata={'relevance_score': .9}) for _ in range(2)]
        path = 'application.flow.step_node.reranker_node.impl.base_reranker_node'
        with patch(path + '.get_model_instance_by_model_workspace_id') as loader:
            loader.return_value.compress_documents.return_value = docs
            result = node.execute('问题', {'top_n': 3, 'similarity': .1, 'max_paragraph_char_number': 5000,
                                  'context_policy': CONFIG},
                                  [p.to_dict() for p in paragraphs()], 'model', True)
        self.assertEqual(len(result.node_variable['result_list']), 1)
        self.assertEqual(result.node_variable['result_list'][0]['metadata']['id'], '0')
        self.assertEqual(result.node_variable['result'], '同一条预约规则')

    def test_search_node_filters_actual_output_and_replay(self):
        node = BaseSearchKnowledgeNode.__new__(BaseSearchKnowledgeNode)
        node.context = {}
        node.workflow_manage = SimpleNamespace(get_body=lambda: {'workspace_id': 'default'})
        node.node_params_serializer = SimpleNamespace(data={'knowledge_setting': {'max_paragraph_char_number': 5000,
                                                                                'context_policy': CONFIG}})
        path = 'application.flow.step_node.search_knowledge_node.impl.base_search_knowledge_node'
        rows = [p.to_dict() for p in paragraphs()]
        with patch(path + '.filter_authorized_ids', return_value=['kb']), \
             patch(path + '.get_embedding_id', return_value='model'), \
             patch(path + '.get_model_instance_by_model_workspace_id'), \
             patch(path + '.DatabaseModelManage.get_model', return_value=None), \
             patch(path + '.QuerySet', return_value=MagicMock()), \
             patch(path + '.connection'), patch(path + '.VectorStore') as vector, \
             patch.object(node, 'list_paragraph', return_value=rows), \
             patch.object(node, 'reset_paragraph', side_effect=lambda row, _: row):
            vector.get_embedding_vector.return_value.query.return_value = []
            result = node.execute(['kb'], {'top_n': 5, 'similarity': .2, 'search_mode': 'embedding',
                                          'max_paragraph_char_number': 5000, 'context_policy': CONFIG},
                                  '问题', True, 'custom', 'knowledge', [])
        data = result.node_variable
        self.assertEqual(len(data['paragraph_list']), 1)
        self.assertEqual(data['data'].count('同一条预约规则'), 1)
        node.save_context(data, None)
        self.assertEqual(node.context['data'], data['data'])
        self.assertEqual(node.context['context_processing'], data['context_processing'])

    def test_direct_return_remains_available_even_when_budget_is_tiny(self):
        step = BaseGenerateHumanMessageStep()
        args = self.arguments()
        args['paragraph_list'][0].hit_handling_method = 'directly_return'
        args['paragraph_list'][0].directly_return_similarity = .5
        manager = SimpleNamespace(context={**args, 'context_policy': {**CONFIG, 'token_budget': 1}})
        step.valid_args(manager)
        step._run(manager)
        self.assertEqual(len(manager.context['paragraph_list']), 2)
        self.assertEqual(manager.context['paragraph_list'][0].hit_handling_method, 'directly_return')
        self.assertNotIn('context_processing', manager.context)

    def test_disabled_reranker_preserves_original_truncation(self):
        node = BaseRerankerNode.__new__(BaseRerankerNode)
        node.context = {}
        node.workflow_manage = SimpleNamespace(get_body=lambda: {'workspace_id': 'default'})
        path = 'application.flow.step_node.reranker_node.impl.base_reranker_node'
        documents = [Document(page_content='abcdef', metadata={'relevance_score': .9})]
        with patch(path + '.get_model_instance_by_model_workspace_id') as loader:
            loader.return_value.compress_documents.return_value = documents
            result = node.execute('问题', {'top_n': 3, 'similarity': .1, 'max_paragraph_char_number': 3,
                                  'context_policy': {'enabled': False}}, ['abcdef'], 'model', True)
        self.assertEqual(result.node_variable['result'], 'abc')
        self.assertNotIn('context_processing', result.node_variable)

    def test_old_pipeline_settings_need_no_new_fields(self):
        step = BaseGenerateHumanMessageStep()
        manager = SimpleNamespace(context=self.arguments())
        step.valid_args(manager)
        step._run(manager)
        self.assertEqual(manager.context['message_list'][-1].content.count('同一条预约规则'), 2)
        self.assertNotIn('context_processing', manager.context)

    def test_normalized_source_labels_removed_only_from_comparison(self):
        args = self.arguments()
        args['paragraph_list'][0].content = '[D-one] **最多借５本**。'
        args['paragraph_list'][1].content = '[D-two] 最多借5本。'
        step = BaseGenerateHumanMessageStep()
        manager = SimpleNamespace(context={**args, 'context_policy': CONFIG})
        step.valid_args(manager)
        step._run(manager)
        message = manager.context['message_list'][-1].content
        self.assertIn('[D-one] **最多借５本**。', message)
        self.assertNotIn('[D-two]', message)
        self.assertEqual(manager.context['paragraph_list'][0].id, '0')
        mapping = step.get_details(manager)['context_processing']['mapping']
        self.assertEqual(mapping[1]['retained_id'], '0')
        self.assertEqual(mapping[1]['original_id'], '1')

    def test_containment_sends_complete_original_with_extra_facts(self):
        args = self.arguments()
        args['paragraph_list'][0].content = '[D-one] 青禾图书室的借期为21天。'
        args['paragraph_list'][1].content = '[D-two] 青禾图书室的借期为21天。青禾图书室的容量为6人。'
        step = BaseGenerateHumanMessageStep()
        manager = SimpleNamespace(context={**args, 'context_policy': CONFIG})
        step.valid_args(manager)
        step._run(manager)
        self.assertEqual(manager.context['message_list'][-1].content,
                         '<data>:[D-two] 青禾图书室的借期为21天。青禾图书室的容量为6人。</data>\n问题')
        self.assertEqual([p.id for p in manager.context['paragraph_list']], ['1'])
        self.assertEqual(step.get_details(manager)['context_processing']['mapping'][0]['reason'], 'contained')

    def test_no_removal_keeps_original_model_message_and_history(self):
        args = self.arguments()
        args['paragraph_list'][0].content = '第一份资料'
        args['paragraph_list'][0].similarity = .1
        args['paragraph_list'][1].content = '第二份资料'
        args['paragraph_list'][1].similarity = .9
        old = BaseGenerateHumanMessageStep().execute(**args)
        new = BaseGenerateHumanMessageStep().execute(**args, context_policy=CONFIG)
        self.assertEqual(new, old)


class SemanticRuntimeIntegrationTests(SimpleTestCase):
    def setUp(self):
        import json
        import tempfile
        import time
        from pathlib import Path
        from application.context.reviewed import pair_key
        from application.context.semantic import digest, evidence
        self.rows = [p.to_dict() for p in paragraphs()]
        for row, content in zip(self.rows, ['阅览室禁止吸烟。', '阅览室内不得吸烟。']):
            row.update(content=content, title='规则')
        a, b = sorted(map(evidence, self.rows), key=digest)
        def judge(a, b):
            return dict(scope_match=True, a_entails_b=True, b_entails_a=True, conflict=False, uncertain=False,
                        reason='同义', a_quotes=[a['content']], b_quotes=[b['content']])
        value = {'forward': judge(a, b), 'backward': judge(b, a)}
        versions = {'judge': 'j', 'embedding': 'e'}
        key = pair_key(a, b, 'default/reviewed-context', versions)
        scope = dict(namespace='default/reviewed-context', versions=versions,
                     model_bindings=[{'id': 'model', 'revision': 'rev'}], approvals={key: digest(value)},
                     entries={key: {'value': value, 'created': time.time()}})
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'registry.json'
        path.write_text(json.dumps({'schema': 1, 'scopes': {'default': scope}}))
        for patcher in [patch.dict('os.environ', {'MAXKB_SEMANTIC_REGISTRY': str(path)}),
                        patch('application.context.runtime.model_revision', return_value='rev')]:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.config = {**CONFIG, 'semantic_enabled': True}

    def test_live_pipeline_uses_workspace_and_filters_actual_model_message(self):
        args = ContextIntegrationTests().arguments()
        for paragraph, row in zip(args['paragraph_list'], self.rows):
            paragraph.content, paragraph.title = row['content'], row['title']
        manager = SimpleNamespace(context={**args, 'workspace_id': 'default', 'context_policy': self.config})
        step = BaseGenerateHumanMessageStep()
        step.valid_args(manager)
        step._run(manager)
        self.assertEqual(len(manager.context['paragraph_list']), 1)
        self.assertNotIn('不得吸烟', manager.context['message_list'][-1].content)
        audit = step.get_details(manager)['context_processing']
        self.assertEqual(audit['semantic']['actual_removed_count'], 1)
        self.assertEqual(audit['mapping'][1]['retained_id'], '0')

    def test_reranker_uses_original_fields_for_approved_hash(self):
        node = BaseRerankerNode.__new__(BaseRerankerNode)
        node.context = {}
        node.workflow_manage = SimpleNamespace(get_body=lambda: {'workspace_id': 'default'})
        docs = [Document(page_content=r['title'] + r['content'], metadata={**r, 'relevance_score': .9})
                for r in self.rows]
        path = 'application.flow.step_node.reranker_node.impl.base_reranker_node'
        with patch(path + '.get_model_instance_by_model_workspace_id') as loader:
            loader.return_value.compress_documents.return_value = docs
            result = node.execute('可以吸烟吗', {'top_n': 3, 'similarity': .1, 'max_paragraph_char_number': 5000,
                                             'context_policy': self.config}, self.rows, 'model', True)
        self.assertEqual(len(result.node_variable['result_list']), 1)
        self.assertEqual(result.node_variable['context_processing']['semantic']['actual_removed_count'], 1)
        self.assertEqual(result.node_variable['result'], '规则阅览室禁止吸烟。')

    def test_policy_switch_roundtrips_and_rejects_bad_value(self):
        from application.context.serializers import ContextPolicySerializer
        serializer = ContextPolicySerializer(data=self.config)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertTrue(serializer.data['semantic_enabled'])
        self.assertFalse(ContextPolicySerializer(data={**self.config, 'semantic_enabled': 'invalid'}).is_valid())


    def test_reranker_title_only_is_preserved_and_output_metadata_stays_sanitized(self):
        node = BaseRerankerNode.__new__(BaseRerankerNode)
        node.context = {}
        node.workflow_manage = SimpleNamespace(get_body=lambda: {'workspace_id': 'default'})
        rows = [{'title': '标题也是证据', 'content': '', 'meta': {'allow_download': False, 'url': 'private'}}]
        docs = [Document(page_content='标题也是证据', metadata={**rows[0], 'relevance_score': .9})]
        path = 'application.flow.step_node.reranker_node.impl.base_reranker_node'
        for enabled in (False, True):
            with patch(path + '.get_model_instance_by_model_workspace_id') as loader:
                loader.return_value.compress_documents.return_value = docs
                result = node.execute('问题', {'top_n': 3, 'similarity': .1, 'max_paragraph_char_number': 5000,
                                             'context_policy': {**self.config, 'enabled': enabled}}, rows, 'model', True)
            self.assertEqual(result.node_variable['result'], '标题也是证据')
            self.assertEqual(result.node_variable['result_list'][0]['metadata']['meta'], {'allow_download': False})
            self.assertEqual(rows[0]['meta']['url'], 'private')
