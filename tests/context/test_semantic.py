"""Observe-only semantic comparison: never replace evidence on a model verdict."""
import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest


def paragraph(pid, content, **extra):
    return {'id': pid, 'document_id': 'doc-' + pid, 'knowledge_id': 'kb', 'title': '规则',
            'content': content, **extra}


class SemanticTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module('application.context.semantic')
        except ImportError:
            self.fail('semantic observer is not implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = self.module.PairCache(Path(self.tmp.name) / 'pairs.sqlite')
        self.calls = []
        self.items = [paragraph('a', '普通读者最多借5本。'), paragraph('b', '普通读者的借阅上限为5本。')]
        self.versions = {'judge': 'judge-v1', 'embedding': 'embedding-v1'}

    def judgement(self, a, b):
        self.calls.append((a['id'], b['id']))
        return {'scope_match': True, 'a_entails_b': True, 'b_entails_a': True,
                'conflict': False, 'uncertain': False, 'reason': '相同主体和借阅上限。',
                'a_quotes': [a['content']], 'b_quotes': [b['content']]}

    def inspect(self, items=None, **kwargs):
        return self.module.observe_pairs(items or self.items, [[1., 0.], [.99, .01]],
            judge=kwargs.pop('judge', self.judgement), cache=self.cache,
            namespace=kwargs.pop('namespace', 'workspace/user-scope'),
            versions=kwargs.pop('versions', self.versions), **kwargs)

    def test_paraphrase_is_only_a_review_proposal_and_input_not_mutated(self):
        before = copy.deepcopy(self.items)
        out = self.inspect()
        self.assertEqual(out['pairs'][0]['decision'], 'review_equivalent')
        self.assertEqual(out['actual_removed_count'], 0)
        self.assertEqual(self.items, before)
        self.assertEqual(len(self.calls), 2)  # Independent reversed-input confirmation.

    def test_repeated_and_reversed_pairs_use_same_direction_safe_cache(self):
        self.inspect()
        result = self.inspect(list(reversed(self.items)))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(result['cache_hits'], 1)
        self.assertEqual(result['pairs'][0]['decision'], 'review_equivalent')

    def test_content_title_meta_namespace_and_version_changes_invalidate_cache(self):
        self.inspect()
        for field, value in [('content', '每名普通读者借书不得超过5本。'),
                             ('title', '新规则'), ('meta', {'effective': '2026'})]:
            changed = copy.deepcopy(self.items)
            for item in changed:
                if field != 'content' or item['id'] == 'a':
                    item[field] = value
            self.inspect(changed)
        self.inspect(namespace='another/user')
        self.inspect(versions={**self.versions, 'judge': 'judge-v2'})
        self.assertEqual(len(self.calls), 12)

    def test_numeric_or_scope_mismatch_does_not_call_judge(self):
        for field, value in [('content', '普通读者最多借8本。'), ('knowledge_id', 'other'),
                             ('title', '儿童规则'), ('meta', {'date': '2025'})]:
            changed = copy.deepcopy(self.items)
            changed[1][field] = value
            out = self.inspect(changed)
            self.assertEqual(out['pairs'][0]['decision'], 'keep_guarded')
        self.assertEqual(self.calls, [])

    def test_low_similarity_and_invalid_vectors_do_not_call_model(self):
        args = dict(judge=self.judgement, cache=self.cache, namespace='test', versions=self.versions)
        out = self.module.observe_pairs(self.items, [[1., 0.], [0., 1.]], **args)
        self.assertEqual(out['pairs'], [])
        for vectors in [[[1.], [1., 2.]], [[float('nan')], [1.]], [[0.], [1.]]]:
            with self.subTest(vectors=vectors):
                with self.assertRaises(ValueError):
                    self.module.observe_pairs(self.items, vectors, **args)
        self.assertEqual(self.calls, [])

    def test_one_way_and_uncertain_relations_never_become_equivalence(self):
        def one_way(a, b):
            result = self.judgement(a, b)
            result['a_entails_b'] = a['id'] == 'a'
            result['b_entails_a'] = b['id'] == 'a'
            return result
        self.assertEqual(self.inspect(judge=one_way)['pairs'][0]['decision'], 'keep_one_way')
        self.assertEqual(len(self.calls), 2)

    def test_orientation_disagreement_is_cached_only_as_keep_uncertain(self):
        def inconsistent(a, b):
            result = self.judgement(a, b)
            result['a_entails_b'] = True
            result['b_entails_a'] = False
            return result
        out = self.inspect(judge=inconsistent)
        self.assertEqual(out['pairs'][0]['decision'], 'keep_uncertain')
        repeated = self.inspect(judge=inconsistent)
        self.assertEqual(repeated['pairs'][0]['decision'], 'keep_uncertain')
        self.assertEqual(repeated['cache_hits'], 1)
        self.assertIn('judgement', out['pairs'][0])
        self.assertIn('reverse_judgement', out['pairs'][0])
        self.assertEqual(repeated['pairs'][0]['judgement'], out['pairs'][0]['judgement'])
        self.assertEqual(repeated['pairs'][0]['reverse_judgement'], out['pairs'][0]['reverse_judgement'])
        self.assertEqual(len(self.calls), 2)

    def test_invalid_json_unknown_fields_and_fake_quotes_fail_closed(self):
        def malformed(a, b):
            result = self.judgement(a, b)
            result['a_quotes'] = ['不存在的证据']
            return result
        out = self.inspect(judge=malformed)
        self.assertEqual(out['pairs'][0]['decision'], 'keep_error')
        valid = self.judgement(*self.items)
        for value in ['not json', {**valid, 'scope_match': 'true'}, {**valid, 'delete': True}]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.module.validate_judgement(value, *self.items)

    def test_judge_exception_is_sanitized_and_not_cached(self):
        def fail(a, b):
            raise RuntimeError('private credential material')
        out = self.inspect(judge=fail)
        self.assertEqual(out['pairs'][0]['decision'], 'keep_error')
        self.assertNotIn('private', json.dumps(out))
        self.assertEqual(self.inspect()['cache_hits'], 0)

    def test_observer_wraps_existing_processor_without_changing_model_input(self):
        from application.context.processor import process_context
        original = process_context(self.items, {'enabled': True})
        out = self.module.observe_context(self.items, [[1., 0.], [.99, .01]], {'enabled': True},
            judge=self.judgement, cache=self.cache, namespace='test', versions=self.versions)
        self.assertEqual(out['text'], original['text'])
        self.assertEqual(out['audit'], original['audit'])
        self.assertTrue(all(x is y for x, y in zip(out['retained'], original['retained'])))
        self.assertEqual(out['semantic_observation']['actual_removed_count'], 0)

    def test_expired_or_corrupt_cache_is_not_reused(self):
        self.cache.set('test-key', {'value': 1}, now=1)
        self.assertIsNone(self.cache.get('test-key', now=90000))
        self.assertEqual(self.cache.get('test-key', now=2), {'value': 1})

    def test_pair_budget_and_size_bound_model_calls(self):
        items = [paragraph(str(i), '同一条规则') for i in range(4)]
        out = self.module.observe_pairs(items, [[1., 0.]] * 4, judge=self.judgement, cache=self.cache,
            namespace='test', versions=self.versions, max_pairs=2)
        self.assertEqual(out['candidate_count'], 6)
        self.assertEqual(out['evaluated_pair_count'], 2)
        self.assertEqual(len(self.calls), 4)
        oversized = copy.deepcopy(self.items)
        oversized[0]['content'] = '字' * 3000
        self.assertEqual(self.inspect(oversized)['pairs'][0]['decision'], 'keep_guarded')

    def test_observation_preserves_rendered_envelopes_and_character_budget(self):
        from application.context.processor import process_context
        def render(p):
            return '<data>' + p['title'] + ':' + p['content'] + '</data>'
        expected = process_context(self.items, {'enabled': True}, render=render, max_chars=500, separator='|')
        out = self.module.observe_context(self.items, [[1., 0.], [.99, .01]], {'enabled': True},
            judge=self.judgement, cache=self.cache, namespace='test', versions=self.versions,
            render=render, max_chars=500, separator='|')
        self.assertEqual(out['text'], expected['text'])
        self.assertEqual(out['audit'], expected['audit'])
        self.assertEqual(out['semantic_observation']['pairs'][0]['decision'], 'review_equivalent')

    def test_judge_cannot_mutate_nested_original_metadata(self):
        items = copy.deepcopy(self.items)
        for item in items:
            item['meta'] = {'scope': ['adult']}
        before = copy.deepcopy(items)
        def mutating(a, b):
            result = self.judgement(a, b)
            a['meta']['scope'].append('child')
            return result
        self.inspect(items, judge=mutating)
        self.assertEqual(items, before)

    def test_cache_reopens_and_stale_records_are_cleaned(self):
        self.inspect()
        reopened = self.module.PairCache(self.cache.path)
        self.cache = reopened
        self.inspect()
        self.assertEqual(len(self.calls), 2)
        self.cache.set('expired', {'value': 1}, now=1)
        self.cache = self.module.PairCache(self.cache.path)
        self.assertIsNone(self.cache.get('expired', now=2))
