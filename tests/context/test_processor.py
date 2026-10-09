import copy
import importlib
import unittest


def row(pid, text, score=None, document='doc'):
    return {'id': pid, 'document_id': document, 'knowledge_id': 'kb', 'content': text,
            'title': '', 'similarity': score}


class ContextTests(unittest.TestCase):
    def setUp(self):
        try:
            self.process = importlib.import_module('application.context.processor').process_context
        except ImportError:
            self.fail('Context processor not implemented')
        self.config = {'enabled': True, 'token_budget': 2048, 'similarity_threshold': .9}

    def run_rows(self, rows, **config):
        return self.process(rows, {**self.config, **config}, max_chars=5000)

    def test_disabled_preserves_identity_and_order(self):
        rows = [row('a', 'hello'), row('b', 'hello')]
        self.assertIs(self.run_rows(rows, enabled=False)['retained'], rows)

    def test_exact_duplicates_keep_best_source_and_mapping(self):
        rows = [row('a', '预约  开放', .5), row('b', '预约 开放', .9, 'other')]
        original = copy.deepcopy(rows)
        out = self.run_rows(rows)
        self.assertEqual([p['id'] for p in out['retained']], ['b'])
        self.assertEqual(out['audit']['mapping'][0]['retained_id'], 'b')
        self.assertEqual(out['audit']['mapping'][0]['original_id'], 'a')
        self.assertEqual(out['audit']['mapping'][0]['document_id'], 'doc')
        self.assertEqual(out['audit']['mapping'][0]['reason'], 'duplicate')
        self.assertEqual(rows, original)

    def test_near_duplicate_punctuation_but_not_changed_facts(self):
        a = '预约成功后，请在周一上午到服务中心领取凭证。'
        b = '预约成功后,请在周一上午到服务中心领取凭证。'
        out = self.run_rows([row('a', a), row('b', b)])
        self.assertEqual(len(out['retained']), 1)
        for changed in [a.replace('周一', '周二'), a.replace('请在', '请勿在'), a + '仅限成人。']:
            self.assertEqual(len(self.run_rows([row('a', a), row('b', changed)])['retained']), 2)

    def test_numeric_and_comparison_changes_preserved(self):
        for a, b in [('最多20人', '最多30人'), ('x > 3', 'x < 3'), ('1.5小时', '15小时')]:
            self.assertEqual(len(self.run_rows([row('a', a), row('b', b)])['retained']), 2)

    def test_missing_scores_uses_original_order(self):
        out = self.run_rows([row('a', 'same'), row('b', 'same', .99)])
        self.assertEqual(out['retained'][0]['id'], 'a')

    def test_empty_and_blank(self):
        self.assertEqual(self.run_rows([])['audit']['retained_count'], 0)
        out = self.run_rows([row('a', '  ')])
        self.assertEqual(out['retained'], [])
        self.assertEqual(out['audit']['mapping'][0]['reason'], 'empty')

    def test_budget_keeps_whole_chunks_and_audits_tail(self):
        out = self.run_rows([row('a', 'long ' * 100), row('tail', '关键事实')], token_budget=20)
        self.assertEqual([p['id'] for p in out['retained']], ['tail'])
        self.assertEqual(out['audit']['mapping'][0]['reason'], 'budget')
        self.assertIsNone(out['audit']['mapping'][0]['retained_id'])
        self.assertLessEqual(out['audit']['estimated_retained_tokens'], 20)

    def test_no_dangling_mapping_when_representative_over_budget(self):
        out = self.run_rows([row('a', 'z' * 200), row('b', 'z' * 200)], token_budget=1)
        self.assertTrue(all(x['retained_id'] is None for x in out['audit']['mapping']))

    def test_source_less_chunks_do_not_gain_invented_ids(self):
        out = self.run_rows([{'content': 'hello'}, {'content': 'hello'}])
        self.assertIsNone(out['audit']['mapping'][0]['original_id'])
        self.assertNotIn('id', out['retained'][0])

    def test_invalid_config_rejected(self):
        for config in [{'token_budget': 0}, {'similarity_threshold': float('nan')}, {'enabled': 'yes'}]:
            with self.assertRaises(ValueError):
                self.run_rows([], **config)

    def test_rendered_envelopes_count_towards_both_budgets(self):
        rows = [row('a', '你好'), row('b', '再见')]
        out = self.process(rows, self.config, max_chars=17, render=lambda p: '<data>'+p['content']+'</data>')
        self.assertLessEqual(len(out['text']), 17)
        self.assertEqual(len(out['retained']), 1)

    def test_incomparable_score_fields_do_not_reorder(self):
        a, b = row('a', 'same', .1), row('b', 'same', None)
        b['relevance_score'] = .99
        self.assertEqual(self.run_rows([a, b])['retained'][0]['id'], 'a')

    def test_high_score_tail_survives_budget(self):
        rows = [row('first', '甲' * 20, .1), row('tail', '关键事实', .9)]
        out = self.run_rows(rows, token_budget=20)
        self.assertEqual([p['id'] for p in out['retained']], ['tail'])
        self.assertEqual(out['audit']['mapping'][1]['original_id'], 'tail')

    def test_enumeration_digits_are_not_merged(self):
        text = '服务中心办理业务时，请前往1、2号窗口领取申请材料，其他窗口不办理此业务。'
        out = self.run_rows([row('a', text), row('b', text.replace('1、2', '12'))])
        self.assertEqual(len(out['retained']), 2)

    def test_oversize_duplicate_does_not_block_fitting_copy(self):
        out = self.process([row('a', '证据' + ' ' * 500 + '成立', .9), row('b', '证据 成立', .8)],
                           self.config, max_chars=50)
        self.assertEqual([r['id'] for r in out['retained']], ['b'])
