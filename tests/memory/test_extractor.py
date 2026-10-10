import unittest
from application.conversation_memory.extractor import parse_operations
from application.conversation_memory.types import MemorySnapshot


class ExtractorTests(unittest.TestCase):
    def test_invalid_json_rejected(self):
        self.assertEqual(parse_operations('not json', '预算3000', MemorySnapshot(), 'turn').status, 'invalid')

    def test_fabricated_quote_rejected(self):
        text = '{"operations":[{"action":"add","entity":"旅行","attribute":"预算","value":"4000","quote":"预算4000"}]}'
        self.assertEqual(parse_operations(text, '预算3000', MemorySnapshot(), 'turn').status, 'invalid')

    def test_explicit_value_and_quote(self):
        text = '{"operations":[{"action":"add","entity":"旅行","attribute":"预算","value":"3000","quote":"预算3000"}]}'
        result = parse_operations(text, '预算3000', MemorySnapshot(), 'turn')
        self.assertEqual(result.operations[0].value, '3000')
        self.assertEqual(result.operations[0].source, 'turn')

    def test_model_cannot_claim_explicit_authority(self):
        text = '{"operations":[{"action":"add","entity":"旅行","attribute":"预算","value":"3000","quote":"预算3000","explicit":true}]}'
        self.assertEqual(parse_operations(text, '预算3000', MemorySnapshot(), 'turn').status, 'invalid')

    def test_hypothetical_correction_does_not_mutate(self):
        from application.conversation_memory.policy import apply_operations
        from application.conversation_memory.types import Operation
        state = apply_operations(MemorySnapshot(), [Operation('add', entity='旅行', attribute='预算',
                                 value='3000', quote='预算3000')]).snapshot
        import json
        text = json.dumps({'operations': [{'action': 'replace', 'target': state.facts[0]['id'],
                          'value': '4000', 'quote': '如果预算改为4000呢？'}]})
        result = parse_operations(text, '如果预算改为4000呢？', state, 'turn')
        self.assertEqual(result.operations, [])

    def test_unique_ordinal_has_real_historical_source(self):
        import json
        text = json.dumps({'operations': [{'action': 'add', 'entity': '当前任务', 'attribute': '选择',
                          'value': 'Beta', 'quote': '选择第二款'}]})
        result = parse_operations(text, '选择第二款', MemorySnapshot(), 'turn',
                                  evidence=[{'id': 'old', 'question': '两款相机', 'answer': '1. Alpha\n2. Beta'}])
        self.assertEqual(result.operations[0].action, 'add')
        self.assertEqual(result.operations[0].value, 'Beta')

    def test_optional_null_target_on_add(self):
        text = '{"operations":[{"action":"add","entity":"当前任务","attribute":"旅行预算","value":"3000元","target":null,"quote":"我的旅行预算是3000元"}]}'
        result = parse_operations(text, '我的旅行预算是3000元，请记住。', MemorySnapshot(), 'turn')
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.operations[0].target, '')

    def test_wrong_entity_target_cannot_replace_confirmed_fact(self):
        import json
        from application.conversation_memory.types import Operation
        from application.conversation_memory.policy import apply_operations
        state = apply_operations(MemorySnapshot(), [Operation('add', entity='相机', attribute='预算', value='3000'),
                              Operation('add', entity='电脑', attribute='预算', value='8000')]).snapshot
        text = json.dumps({'operations': [{'action': 'replace', 'target': state.facts[0]['id'],
                          'value': '9000', 'quote': '电脑预算改为9000'}]})
        result = parse_operations(text, '电脑预算改为9000', state, 'turn')
        self.assertEqual(result.status, 'invalid')

    def test_hypothetical_add_not_confirmed(self):
        text = '{"operations":[{"action":"add","entity":"当前任务","attribute":"预算","value":"3000","quote":"如果预算3000呢？"}]}'
        result = parse_operations(text, '如果预算3000呢？', MemorySnapshot(), 'turn')
        self.assertEqual(result.operations, [])

    def test_quoted_example_not_confirmed(self):
        text = '{"operations":[{"action":"add","entity":"当前任务","attribute":"预算","value":"3000","quote":"预算3000"}]}'
        result = parse_operations(text, '例如客户说“预算3000”时怎么办', MemorySnapshot(), 'turn')
        self.assertEqual(result.operations, [])

    def test_question_cannot_create_new_condition(self):
        import json
        text = json.dumps({'operations':[{'action':'pending','entity':'背包','attribute':'颜色',
                                         'value':'黑色吗？','quote':'颜色必须黑色吗？'}]})
        result = parse_operations(text, '背包还有什么要求，颜色必须黑色吗？', MemorySnapshot(), 'turn')
        self.assertEqual(result.operations, [])

    def test_ordinal_literal_resolves_only_unique_explicit_choice(self):
        import json
        text = json.dumps({'operations':[{'action':'add','entity':'书桌','attribute':'选择',
                                         'value':'第二款','quote':'我选择第二款作为书桌。'}]})
        evidence = [{'id':'old','question':'列出两款','answer':'1. 松木书桌\n2. 橡木书桌'}]
        result = parse_operations(text, '我选择第二款作为书桌。', MemorySnapshot(), 'turn', evidence)
        self.assertEqual(result.operations[0].value, '橡木书桌')
        self.assertEqual(result.operations[0].action, 'add')
        self.assertEqual(result.operations[0].references, [{'record_id':'old','quote':'橡木书桌'}])
        evidence.append({'id':'other','question':'其他选择','answer':'1. A\n2. B'})
        ambiguous = parse_operations(text, '我选择第二款作为书桌。', MemorySnapshot(), 'turn', evidence)
        self.assertEqual(ambiguous.operations[0].action, 'pending')

    def test_mixed_question_retains_independent_declarative_quote(self):
        import json
        text = json.dumps({'operations':[{'action':'add','entity':'台灯','attribute':'预算',
                                         'value':'400元','quote':'台灯预算400元'}]})
        result = parse_operations(text, '台灯预算400元，哪款合适？', MemorySnapshot(), 'turn')
        self.assertEqual(result.operations[0].action, 'add')

    def test_question_mark_omitted_from_model_quote_still_does_not_write(self):
        import json
        text = json.dumps({'operations':[{'action':'add','entity':'旅行','attribute':'预算',
                                         'value':'4000元','quote':'预算是4000元'}]})
        self.assertEqual(parse_operations(text, '旅行预算是4000元吗？', MemorySnapshot(), 'turn').operations, [])

    def test_later_hypothesis_does_not_discard_explicit_fact(self):
        import json
        text = json.dumps({'operations':[{'action':'add','entity':'旅行','attribute':'预算',
                                         'value':'4000元','quote':'旅行预算4000元'}]})
        result = parse_operations(text, '旅行预算4000元，如果不够再讨论。', MemorySnapshot(), 'turn')
        self.assertEqual(result.operations[0].action, 'add')

    def test_two_local_ordinals_keep_distinct_choices(self):
        import json
        question = '我选择第一款放客厅，选择第二款放书房。'
        text = json.dumps({'operations':[
            {'action':'add','entity':'客厅','attribute':'书桌','value':'第一款','quote':'我选择第一款放客厅'},
            {'action':'add','entity':'书房','attribute':'书桌','value':'第二款','quote':'选择第二款放书房'}]})
        result = parse_operations(text, question, MemorySnapshot(), 'turn',
            [{'id':'old','answer':'1. 松木书桌\n2. 橡木书桌'}])
        self.assertEqual([op.value for op in result.operations], ['松木书桌','橡木书桌'])

    def test_ambiguous_entity_cannot_be_assigned_to_one_old_budget(self):
        import json
        from application.conversation_memory.policy import apply_operations
        from application.conversation_memory.types import Operation
        state = apply_operations(MemorySnapshot(), [Operation('add',entity='耳机',attribute='预算',value='900元'),
            Operation('add',entity='键盘',attribute='预算',value='600元')]).snapshot
        text = json.dumps({'operations':[{'action':'replace','target':state.facts[0]['id'],
            'value':'750元','quote':'那个预算改为750元'}]})
        result = parse_operations(text, '那个预算改为750元。', state, 'turn')
        changed = apply_operations(state,result.operations).snapshot
        self.assertEqual([(f['value'],f['status']) for f in changed.facts[:2]],
                         [('900元','confirmed'),('600元','confirmed')])
        self.assertEqual(changed.facts[-1]['entity'], '未明确对象')
        self.assertEqual(changed.facts[-1]['status'], 'pending')

    def test_ambiguous_generic_entity_keys_do_not_pin_a_target(self):
        import json
        from application.conversation_memory.policy import apply_operations
        from application.conversation_memory.types import Operation
        state = apply_operations(MemorySnapshot(), [Operation('add',entity='当前任务',attribute='耳机预算',value='900元'),
            Operation('add',entity='当前任务',attribute='键盘预算',value='600元')]).snapshot
        text = json.dumps({'operations':[{'action':'replace','target':state.facts[0]['id'],
            'value':'750元','quote':'那个预算改为750元。'}]})
        changed = apply_operations(state,parse_operations(text,'那个预算改为750元。',state,'turn').operations).snapshot
        self.assertEqual([(f['value'],f['status']) for f in changed.facts[:2]],
                         [('900元','confirmed'),('600元','confirmed')])
        self.assertEqual(changed.facts[-1]['entity'],'未明确对象')
        self.assertEqual(changed.facts[-1]['attribute'],'待确认更正')

    def test_explicit_revoke_accepts_attribute_requirement_suffix(self):
        import json
        from application.conversation_memory.policy import apply_operations
        from application.conversation_memory.types import Operation
        state = apply_operations(MemorySnapshot(), [Operation('add',entity='当前任务',attribute='颜色要求',value='红色'),
            Operation('add',entity='当前任务',attribute='尺寸要求',value='20寸')]).snapshot
        text = json.dumps({'operations':[{'action':'revoke','target':state.facts[0]['id'],
            'value':'红色','quote':'不再要求行李箱颜色为红色。'}]})
        result = parse_operations(text,'不再要求行李箱颜色为红色。',state,'turn')
        self.assertTrue(result.operations[0].explicit)
        changed = apply_operations(state,result.operations).snapshot
        self.assertEqual([(f['attribute'],f['value']) for f in changed.facts],[('尺寸要求','20寸')])
