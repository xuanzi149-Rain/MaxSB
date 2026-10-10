import unittest
from application.conversation_memory.policy import apply_operations
from application.conversation_memory.types import MemorySnapshot, Operation


class PolicyTests(unittest.TestCase):
    def add(self, entity='旅行', attribute='预算', value='3000'):
        return Operation('add', entity=entity, attribute=attribute, value=value, quote='预算3000', source='turn-1')

    def test_replace_budget_retains_both_sources(self):
        first = apply_operations(MemorySnapshot(), [self.add()]).snapshot
        original = first.facts[0]
        result = apply_operations(first, [Operation('replace', target=original['id'], value='4000',
                                                    quote='预算改为4000', source='turn-2', explicit=True)])
        self.assertEqual([(x['value'], x['status']) for x in result.snapshot.facts], [('4000', 'confirmed')])
        self.assertEqual(result.changes[0]['before']['value'], '3000')
        self.assertEqual(result.changes[0]['before']['source'], 'turn-1')
        self.assertEqual(result.changes[0]['after']['source'], 'turn-2')
        self.assertEqual(first.facts[0]['value'], '3000')

    def test_ambiguous_conflict_requires_confirmation(self):
        first = apply_operations(MemorySnapshot(), [self.add()]).snapshot
        result = apply_operations(first, [self.add(value='4000')])
        self.assertEqual({x['status'] for x in result.snapshot.facts}, {'pending'})
        self.assertEqual({x['value'] for x in result.snapshot.facts}, {'3000', '4000'})

    def test_revoke_excludes_condition(self):
        first = apply_operations(MemorySnapshot(), [self.add(attribute='防水', value='需要')]).snapshot
        result = apply_operations(first, [Operation('revoke', target=first.facts[0]['id'], source='turn-2',
                                                    quote='不再要求防水', explicit=True)])
        self.assertEqual(result.snapshot.facts, [])
        self.assertEqual(result.changes[0]['after']['status'], 'revoked')

    def test_same_attribute_different_entities(self):
        result = apply_operations(MemorySnapshot(), [self.add('相机'), self.add('电脑')])
        self.assertEqual(len(result.snapshot.facts), 2)

    def test_capacity_does_not_drop_existing_facts(self):
        first = apply_operations(MemorySnapshot(), [self.add(str(i)) for i in range(100)]).snapshot
        result = apply_operations(first, [self.add('101')])
        self.assertEqual(result.snapshot.facts, first.facts)
        self.assertEqual(result.rejected, ['capacity'])

    def test_unknown_target_rejected(self):
        result = apply_operations(MemorySnapshot(), [Operation('replace', target='foreign', value='x')])
        self.assertEqual(result.snapshot.facts, [])
        self.assertEqual(result.rejected, ['unknown_target'])


class RevocationContextTests(unittest.TestCase):
    def test_later_fact_and_pending_candidate_suppress_old_revocation(self):
        from application.conversation_memory.policy import revocation_notes
        revoked = {'id': 'one', 'entity': '手表', 'attribute': '防水', 'value': '要求', 'status': 'revoked'}
        events = [{'changes': [{'after': revoked}], 'result_version': 2}]
        self.assertEqual(revocation_notes(events, [dict(revoked, status='confirmed')]), [])
        later = {'changes': [{'after': dict(revoked, status='pending')}], 'result_version': 3}
        self.assertEqual(revocation_notes([later, *events], []), [])
        notes = revocation_notes(events, [])
        self.assertEqual(notes[0]['status'], 'revoked')
        self.assertEqual(notes[0]['value'], '用户已撤销此条件')
