import unittest
from application.retrieval.policy import classify_question


class IntentTests(unittest.TestCase):
    def test_explicit_conversation_controls_skip_knowledge(self):
        for question in ['请先记住前面的要求。', '暂时不要执行任何操作。', '请用简短条目回复。',
                         '补充一个无关安排：我晚上要浇花，这不改变之前的条件。']:
            with self.subTest(question=question):
                self.assertEqual(classify_question(question)[0], 'none')

    def test_mixed_intents_and_corrections_still_retrieve(self):
        for question in ['请用简短条目回复，退货期限是多少？', '先记住：预算改为900元。',
                         '谢谢，不过儿童是否也适用？', '我晚上浇花，订单已经改为五件。',
                         '补充一个无关安排：运费是多少，这不改变之前的条件。']:
            with self.subTest(question=question):
                self.assertNotEqual(classify_question(question)[0], 'none')

    def test_multi_requirement_and_numeric_constraints_are_not_simple(self):
        for question in ['租金及押金是否符合预算？', '重量8千克、长度70厘米是否允许托运？',
                         '折后价格是否低于250元？', '成人与儿童分别能借多少本？']:
            with self.subTest(question=question):
                self.assertNotEqual(classify_question(question)[0], 'simple')

    def test_reference_question_preserves_evidence(self):
        for question in ['上述规则是否也适用？', '按刚才的规定可以吗？']:
            self.assertEqual(classify_question(question)[0], 'unknown')


class DialogueHistoryTests(unittest.TestCase):
    def setUp(self):
        from application.retrieval.dialogue import prepare_history, response_guidance
        self.prepare = prepare_history
        self.guidance = response_guidance
        self.context = '[A] 租赁押金为300元，正常归还后退回。'
        self.turn = {'question': '资料：' + self.context + '\n问题：押金多少？',
                     'raw_question': '押金多少？', 'context': self.context, 'answer': '押金300元。[A]'}

    def test_deduplicates_only_verified_current_evidence(self):
        result, trace = self.prepare([self.turn], self.context, '归还后何时退押金？', True)
        self.assertNotIn(self.context, result[0]['question'])
        self.assertIn('押金多少？', result[0]['question'])
        self.assertEqual(result[0]['answer'], self.turn['answer'])
        self.assertEqual(trace['removed_contexts'], 1)
        self.assertIn(self.context, self.turn['question'])

    def test_disabled_unknown_sources_and_followups_preserve_history(self):
        for enabled, context, question, turn in [
            (False, self.context, '其他问题', self.turn),
            (True, '新的资料', '其他问题', self.turn),
            (True, self.context, '它是多少？', self.turn),
            (True, self.context, '其他问题', {**self.turn, 'context': ''}),
            (True, self.context, '其他问题', {**self.turn, 'raw_question': ''}),
            (True, self.context, '其他问题', {**self.turn, 'question': [{'type': 'image_url'}]}),
        ]:
            result, trace = self.prepare([turn], context, question, enabled)
            self.assertEqual(result, [turn])
            self.assertEqual(trace['removed_contexts'], 0)

    def test_brief_guidance_only_for_pure_controls(self):
        self.assertTrue(self.guidance('请先记住前面的要求。', True))
        self.assertEqual(self.guidance('请先记住前面的要求。', False), '')
        self.assertEqual(self.guidance('请简短回答：成人能否借书？', True), '')


class ComposedControlsTests(unittest.TestCase):
    def test_all_clauses_must_be_pure_controls(self):
        for question in ['请简短回复，先不要执行任何操作。', '我希望用简洁语言回答。',
                         '暂时不需要制定计划，请保留之前的信息。']:
            self.assertEqual(classify_question(question)[0], 'none')
        for question in ['请简短回复，预算调整到八百。', '请简短回复，但需要哪些证件？',
                         '暂时不需要制定计划，订单取消。']:
            self.assertNotEqual(classify_question(question)[0], 'none')


class ContinuityTests(unittest.TestCase):
    def test_business_guidance_preserves_user_corrections_without_brief_constraint(self):
        from application.retrieval.dialogue import dialogue_guidance
        text = dialogue_guidance('能否寄件？', True)
        self.assertIn('最新', text)
        self.assertNotIn('只用一句', text)
        self.assertEqual(dialogue_guidance('能否寄件？', False), '')


class ReviewRegressionTests(unittest.TestCase):
    def test_business_correction_inside_claimed_side_note_is_not_skipped(self):
        self.assertNotEqual(classify_question('补充一个无关安排：收货地址换成北京，这不改变之前的条件。')[0], 'none')

    def test_chinese_quantity_and_second_request_do_not_shrink(self):
        for text in ['八千克的包裹是否可以寄？', '租金是多少，押金也介绍一下。',
                     '八岁的儿童是否需要买票？', '五个人是否能一起入住？', '租期三个月是否能提前退租？']:
            self.assertNotEqual(classify_question(text)[0], 'simple')

    def test_polite_prefix_does_not_hide_reference(self):
        self.assertEqual(classify_question('请问上述规则是否适用？')[0], 'unknown')
        from application.retrieval.dialogue import prepare_history
        context = '[R] 适用条件限定为企业客户和工作日寄件。'
        turns = [{'question': context + '\n哪些人适用？', 'raw_question': '哪些人适用？',
                  'context': context, 'answer': '企业客户。'}]
        self.assertEqual(prepare_history(turns, context, '请问上述规则是否适用？', True)[0], turns)
