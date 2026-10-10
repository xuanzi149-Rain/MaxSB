import copy
import importlib
import unittest


class RetrievalPolicyTests(unittest.TestCase):
    def setUp(self):
        try:
            self.decide = importlib.import_module('application.retrieval.policy').decide_retrieval
        except ImportError:
            self.fail('Dynamic retrieval policy is not implemented')
        self.settings = {'top_n': 5, 'similarity': .4, 'search_mode': 'embedding',
                         'retrieval_policy': {'enabled': True}}

    def test_exact_greeting_skips_but_greeting_with_question_does_not(self):
        for question in ['你好！', '  Hi! ', '谢谢', '再见。']:
            with self.subTest(question=question):
                result = self.decide(question, self.settings)
                self.assertEqual(result['category'], 'none')
                self.assertFalse(result['retrieve'])
                self.assertFalse(result['rerank'])
        result = self.decide('你好，请问借期是多少天？', self.settings)
        self.assertTrue(result['retrieve'])
        self.assertEqual(result['category'], 'simple')

    def test_single_fact_and_comparison_use_distinct_limits(self):
        simple = self.decide('借期是多少天？', self.settings)
        complex_ = self.decide('比较成人和儿童借书的条件', self.settings)
        self.assertEqual((simple['category'], simple['top_n'], simple['rerank']), ('simple', 3, False))
        self.assertEqual((complex_['category'], complex_['top_n'], complex_['rerank']), ('complex', 8, True))
        self.assertEqual(complex_['similarity'], .4)

    def test_unknown_and_followup_preserve_fixed_parameters(self):
        for question in ['', '帮我看看', '它是多少？', '那第二个呢', '这是一个很长但没有明确类别的陈述']:
            with self.subTest(question=question):
                result = self.decide(question, self.settings)
                self.assertEqual(result['category'], 'unknown')
                self.assertEqual(result['top_n'], 5)
                self.assertTrue(result['retrieve'])
                self.assertIsNone(result['rerank'])

    def test_multiple_questions_never_use_single_fact_budget(self):
        for question in ['借期是多少天？最多借几本？', '借期多久，且最多借几本？', 'What is the fee and how long is the loan?']:
            with self.subTest(question=question):
                self.assertEqual(self.decide(question, self.settings)['category'], 'complex')

    def test_disabled_or_old_settings_are_unchanged(self):
        for policy in [None, {'enabled': False}]:
            settings = {**self.settings, 'retrieval_policy': policy}
            before = copy.deepcopy(settings)
            self.assertIsNone(self.decide('你好', settings))
            self.assertEqual(settings, before)

    def test_category_configuration_and_input_are_preserved(self):
        self.settings['retrieval_policy']['simple'] = {'retrieve': True, 'top_n': 7, 'rerank': True}
        before = copy.deepcopy(self.settings)
        result = self.decide('借期是多少天？', self.settings)
        self.assertEqual((result['top_n'], result['rerank']), (7, True))
        self.assertEqual(self.settings, before)
