# coding=utf-8
from uuid import uuid4
from django.test import SimpleTestCase, override_settings
from application.conversation_memory.temporary import TemporaryMemoryStore
from application.conversation_memory.types import Identity, Operation
from application.conversation_memory.policy import apply_operations
from application.conversation_memory.store import MemoryConflict, MemoryDenied


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class TemporaryMemoryTests(SimpleTestCase):
    def test_debug_isolated_and_clear_rejects_inflight(self):
        identity = Identity('app', 'user', 'PLATFORM_USER')
        chat_id = str(uuid4())
        store = TemporaryMemoryStore(identity, chat_id)
        ticket = store.begin_turn(identity, chat_id, str(uuid4()), '预算3000')
        changes = apply_operations(ticket.snapshot, [Operation('add', entity='旅行', attribute='预算',
                                  value='3000', quote='预算3000', source=ticket.event_id)])
        state = store.commit_turn(ticket, changes)
        self.assertEqual(state.facts[0]['value'], '3000')
        other_chat = str(uuid4())
        self.assertEqual(TemporaryMemoryStore(identity, other_chat).read(identity, other_chat).facts, [])
        next_ticket = store.begin_turn(identity, chat_id, str(uuid4()), '预算4000')
        store.clear(identity, chat_id, state.version, str(uuid4()))
        with self.assertRaises(MemoryConflict):
            store.commit_turn(next_ticket, changes)
        self.assertEqual(store.sources(identity, chat_id), [])

    def test_wrong_identity_denied(self):
        identity = Identity('app', 'user', 'PLATFORM_USER')
        store = TemporaryMemoryStore(identity, 'chat')
        with self.assertRaises(MemoryDenied):
            store.read(Identity('app', 'other', 'PLATFORM_USER'), 'chat')
