"""Behavioral regressions for format deduplication and conservative extraction."""
import copy
import unittest

from application.context.processor import process_context


class NormalizationTests(unittest.TestCase):
    def process(self, *texts, titles=None, scores=None, budget=2048):
        rows = [{'id': str(i), 'document_id': 'doc-' + str(i), 'knowledge_id': 'kb',
                 'content': text, 'title': titles[i] if titles else '',
                 'similarity': scores[i] if scores else None} for i, text in enumerate(texts)]
        original = copy.deepcopy(rows)
        result = process_context(rows, {'enabled': True, 'token_budget': budget, 'similarity_threshold': .95})
        self.assertEqual(rows, original)
        for retained in result['retained']:
            self.assertTrue(any(retained is row for row in rows))
        return result

    def test_width_markdown_and_html_duplicates_keep_original_evidence(self):
        a = '[D-one] • 普通读者最多借５本。\n• 普通借期２１天。'
        b = '[D-two] <ul><li>普通读者最多借5本。</li><li>普通借期21天。</li></ul>'
        out = self.process(a, b)
        self.assertEqual([r['id'] for r in out['retained']], ['0'])
        self.assertEqual(out['text'], a)
        self.assertEqual(out['audit']['mapping'][1]['retained_id'], '0')
        self.assertGreater(out['audit']['estimated_saved_tokens'], 0)

    def test_bold_and_fullwidth_title_are_formatting(self):
        out = self.process('**最多借5本**。', '最多借5本。', titles=['规则Ａ', '规则A'])
        self.assertEqual(len(out['retained']), 1)

    def test_leading_source_label_does_not_mask_body_duplicates(self):
        out = self.process('[D-one] 最多借5本。', '[D-two] 最多借5本。')
        self.assertEqual(len(out['retained']), 1)
        self.assertEqual(out['audit']['mapping'][1]['document_id'], 'doc-1')

    def test_source_mentions_inside_facts_are_not_removed(self):
        out = self.process('规则[D-one]已经作废。', '规则[D-two]已经作废。')
        self.assertEqual(len(out['retained']), 2)

    def test_title_scope_and_compatibility_symbols_stay_distinct(self):
        self.assertEqual(len(self.process('最多借5本。', '最多借5本。',
                                         titles=['成人', '儿童'])['retained']), 2)
        for a, b in [('x²', 'x2'), ('1、2号窗口', '12号窗口'), ('1.5小时', '15小时'),
                     ('允许借阅', '不允许借阅'), ('A B', 'AB')]:
            with self.subTest(a=a):
                self.assertEqual(len(self.process(a, b)['retained']), 2)

    def test_table_link_and_code_structure_not_discarded(self):
        for a, b in [('<table><tr><td>甲</td><td>乙</td></tr></table>', '甲乙'),
                     ('[规则](https://a.example)', '[规则](https://b.example)'),
                     ('`a b`', '`ab`')]:
            with self.subTest(a=a):
                self.assertEqual(len(self.process(a, b)['retained']), 2)

    def test_whole_paragraph_covered_by_complete_clauses_is_extracted(self):
        a = '[D-one] 青禾图书室的借阅上限为5本。'
        b = '[D-two] 青禾图书室的借阅上限为5本。青禾图书室的借期为21天。'
        out = self.process(a, b)
        self.assertEqual([r['id'] for r in out['retained']], ['1'])
        self.assertEqual(out['text'], b)
        self.assertEqual(out['audit']['mapping'][0]['reason'], 'contained')
        self.assertEqual(out['audit']['mapping'][0]['retained_id'], '1')

    def test_clause_order_is_not_treated_as_a_set(self):
        a = '先登记。再付款。'
        b = '再付款。先登记。最后取件。'
        self.assertEqual(len(self.process(a, b)['retained']), 2)

    def test_conditions_and_conflicts_block_containment(self):
        a = '青禾图书室的借阅上限为5本。'
        for extra in ['仅限成人。', '如果是儿童，上述规则不适用。', '但预约中的书不可续借。',
                      '以上内容已作废。', '更正：青禾图书室最多借8本。']:
            with self.subTest(extra=extra):
                self.assertEqual(len(self.process(a, a + extra)['retained']), 2)

    def test_partial_overlap_preserves_both_unique_parts(self):
        out = self.process('青禾图书室的借阅上限为5本。青禾图书室周一闭馆。',
                           '青禾图书室的借阅上限为5本。青禾图书室的借期为21天。')
        self.assertEqual(len(out['retained']), 2)

    def test_no_deletion_means_original_order_and_bytes_even_with_scores(self):
        a, b = '甲资料', '乙资料'
        out = self.process(a, b, scores=[.1, .9])
        self.assertEqual(out['text'], '甲资料\n乙资料')
        self.assertEqual([r['id'] for r in out['retained']], ['0', '1'])

    def test_extraction_keeps_remaining_original_order(self):
        out = self.process('青禾图书室的借阅上限为5本。', '乙资料。',
                           '青禾图书室的借阅上限为5本。青禾图书室的借期为21天。', scores=[.8, .1, .9])
        self.assertEqual([r['id'] for r in out['retained']], ['1', '2'])

    def test_over_budget_cover_does_not_remove_fitting_original(self):
        out = self.process('甲资料。', '甲资料。' + '乙' * 100 + '。', budget=20)
        self.assertEqual([r['id'] for r in out['retained']], ['0'])
        self.assertIsNone(out['audit']['mapping'][1]['retained_id'])

    def test_duplicate_chain_always_points_at_retained_source(self):
        a = '青禾图书室的借阅上限为5本。'
        b = a + '青禾图书室的借期为21天。'
        out = self.process(a, b, b + '青禾图书室的容量为6人。')
        self.assertEqual([r['id'] for r in out['retained']], ['2'])
        self.assertEqual([m['retained_id'] for m in out['audit']['mapping']], ['2', '2', '2'])

    def test_content_in_different_knowledge_scopes_is_not_collapsed(self):
        rows = [{'content': '借阅规则。', 'knowledge_id': 'a'},
                {'content': '借阅规则。', 'knowledge_id': 'b'}]
        out = process_context(rows, {'enabled': True})
        self.assertEqual(len(out['retained']), 2)

    def test_numeric_signs_and_code_are_not_formatting(self):
        for a, b in [('- 5摄氏度', '5摄氏度'), ('+ 5', '5'), ('`**x**`', '`x`'),
                     ('```\n- 5\n```', '```\n5\n```'), ('`a  b`', '`a b`')]:
            with self.subTest(a=a):
                self.assertEqual(len(self.process(a, b)['retained']), 2)

    def test_free_text_scope_cannot_be_proved_by_clause_overlap(self):
        for a, b in [('可借5本。', '可借5本。有效期截至2020年。'),
                     ('可借5本。', '错误示例。可借5本。'),
                     ('可借5本。', '可借5本。年满18岁。')]:
            with self.subTest(b=b):
                self.assertEqual(len(self.process(a, b)['retained']), 2)

    def test_typed_fact_scope_conflict_and_unknown_attributes_are_preserved(self):
        a = '青禾图书室的借阅上限为5本。'
        for extra in ['青禾图书室的借阅上限为8本。', '红叶图书室的借期为21天。',
                      '青禾图书室的有效期为20天。', '青禾图书室的年龄要求为18岁。']:
            with self.subTest(extra=extra):
                self.assertEqual(len(self.process(a, a + extra)['retained']), 2)

    def test_final_source_mapping_survives_missing_terminal_period(self):
        a = '青禾图书室的借阅上限为5本。'
        b = a.rstrip('。')
        c = a + '青禾图书室的借期为21天。'
        out = self.process(a, b, c)
        self.assertEqual([r['id'] for r in out['retained']], ['2'])
        self.assertEqual([m['retained_id'] for m in out['audit']['mapping']], ['2', '2', '2'])

    def test_unprovable_mapping_after_replacement_keeps_original_representative(self):
        a = '青禾图书室普通读者的借阅上限为5本。'
        b = '青禾图书室普通读者的借阅上限为5本，。'
        c = a + '青禾图书室普通读者的借期为21天。'
        out = self.process(a, b, c)
        self.assertTrue(all(m['retained_id'] is not None for m in out['audit']['mapping']))
        self.assertNotIn('budget', [m['reason'] for m in out['audit']['mapping']])

    def test_unknown_html_and_processing_instructions_are_opaque(self):
        for a, b in [('<?php echo 5;?>', '<?php echo 6;?>'),
                     ('<code>**x**</code>', '<code>x</code>')]:
            with self.subTest(a=a):
                self.assertEqual(len(self.process(a, b)['retained']), 2)

    def test_enumeration_comma_is_not_deleted(self):
        for comma in [',', '，', '、']:
            out = self.process('允许借阅的范围为中文' + comma + '数学资料。',
                               '允许借阅的范围为中文数学资料。')
            self.assertEqual(len(out['retained']), 2)
