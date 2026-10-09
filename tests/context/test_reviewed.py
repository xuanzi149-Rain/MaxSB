"""Reviewed semantic application must be exact, cache-only and fail closed."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from application.context.semantic import PairCache, digest
from application.context.reviewed import apply_reviewed_context, pair_key


class ReviewedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = PairCache(Path(self.tmp.name) / 'cache.sqlite')
        self.items = [dict(id='a', document_id='a', knowledge_id='k', title='规则', content='阅览室禁止吸烟。'),
                      dict(id='b', document_id='b', knowledge_id='k', title='规则', content='阅览室内不得吸烟。')]
        self.versions = {'judge': 'v1', 'embedding': 'v1'}
        self.value = dict(forward=self.judgement(self.items), backward=self.judgement(self.items[::-1]))
        # Canonical orientation is independent of caller order.
        from application.context.semantic import evidence
        canonical = sorted(map(evidence, self.items), key=digest)
        self.value = dict(forward=self.judgement(canonical), backward=self.judgement(canonical[::-1]))
        self.key = pair_key(*self.items, 'scope', self.versions)
        self.cache.set(self.key, self.value)
        self.approved = {self.key: digest(self.value)}

    @staticmethod
    def judgement(items):
        return dict(scope_match=True, a_entails_b=True, b_entails_a=True, conflict=False, uncertain=False,
                    reason='同义', a_quotes=[items[0]['content']], b_quotes=[items[1]['content']])

    def run_policy(self, **kwargs):
        params = dict(cache=self.cache, approvals=self.approved, namespace='scope', versions=self.versions)
        params.update(kwargs)
        return apply_reviewed_context(self.items, {'enabled': True}, **params)

    def test_approved_equivalence_maps_to_existing_original(self):
        original = deepcopy(self.items)
        result = self.run_policy()
        self.assertEqual([p['id'] for p in result['retained']], ['a'])
        self.assertIs(result['retained'][0], self.items[0])
        self.assertEqual(self.items, original)
        self.assertEqual(result['audit']['mapping'][1]['reason'], 'semantic_duplicate')
        self.assertEqual(result['audit']['mapping'][1]['retained_id'], 'a')
        self.assertEqual(result['semantic_application']['actual_removed_count'], 1)
        self.assertEqual(result['semantic_application']['judge_calls'], 0)

    def test_unapproved_or_changed_scope_or_evidence_keeps_both(self):
        for kwargs in [dict(approvals={}), dict(namespace='elsewhere'), dict(versions={'judge': 'v2', 'embedding': 'v1'})]:
            self.assertEqual(len(self.run_policy(**kwargs)['retained']), 2)
        self.items[1]['content'] += '特殊活动除外。'
        self.assertEqual(len(self.run_policy()['retained']), 2)

    def test_expired_missing_broken_or_changed_cache_keeps_both(self):
        for value in [None, {}, {'forward': {}}, {'forward': self.value['forward'], 'backward': {}}]:
            with patch.object(self.cache, 'get', return_value=value):
                self.assertEqual(len(self.run_policy()['retained']), 2)
        with patch.object(self.cache, 'get', side_effect=OSError('private information')):
            self.assertNotIn('private information', str(self.run_policy()))
            self.assertEqual(len(self.run_policy()['retained']), 2)
        with patch('application.context.semantic.time.time', return_value=10**12):
            self.assertEqual(len(self.run_policy()['retained']), 2)

    def test_review_cannot_override_conflict_or_one_way(self):
        for field in ['conflict', 'uncertain', 'a_entails_b', 'scope_match']:
            value = deepcopy(self.value)
            value['forward'][field] = not value['forward'][field]
            self.cache.set(self.key, value)
            self.approved[self.key] = digest(value)
            self.assertEqual(len(self.run_policy()['retained']), 2)

    def test_disabled_does_not_read_cache(self):
        with patch.object(self.cache, 'get', side_effect=AssertionError('must not access')):
            result = apply_reviewed_context(self.items, {'enabled': False}, cache=self.cache,
                                           approvals=self.approved, namespace='scope', versions=self.versions)
        self.assertIs(result['retained'], self.items)
        self.assertEqual(result['semantic_application']['actual_removed_count'], 0)

    def test_order_budget_render_and_no_transitive_approval(self):
        self.items.reverse()
        result = self.run_policy(render=lambda p: '[' + p['id'] + ']' + p['content'], separator='|')
        self.assertEqual(result['retained'][0]['id'], 'b')
        self.assertTrue(result['text'].startswith('[b]'))
        self.assertEqual(self.run_policy(max_chars=1)['retained'], [])
        self.assertEqual(self.run_policy(max_chars=1)['semantic_application']['actual_removed_count'], 0)
        c = dict(self.items[0], id='c', document_id='c', content='阅览室内请勿吸烟。')
        self.items.append(c)
        self.assertEqual([p['id'] for p in self.run_policy()['retained']], ['b', 'c'])
