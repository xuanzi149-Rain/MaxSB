# coding=utf-8
from uuid import uuid4
from django.test import TestCase
from application.models import Application, Chat
from application.conversation_memory.store import MemoryStore, MemoryConflict, MemoryDenied
from application.conversation_memory.types import Identity, Operation
from application.conversation_memory.policy import apply_operations


class StoreTests(TestCase):
    def setUp(self):
        self.app = Application.objects.create(id=uuid4(), name='memory', workspace_id='default')
        self.chat = Chat.objects.create(application=self.app, chat_user_id='owner', chat_user_type='CHAT_USER')
        self.identity = Identity(str(self.app.id), 'owner', 'CHAT_USER')
        self.store = MemoryStore()

    def begin(self, record=None):
        return self.store.begin_turn(self.identity, str(self.chat.id), str(record or uuid4()), '预算3000')

    def test_source_survives_before_chat_record(self):
        ticket = self.begin()
        self.assertEqual(self.store.sources(self.identity, self.chat.id)[0]['question'], '预算3000')
        self.assertEqual(ticket.version, 0)

    def test_duplicate_cannot_extract_twice(self):
        record = uuid4()
        self.begin(record)
        with self.assertRaises(MemoryConflict):
            self.begin(record)

    def test_clear_rejects_inflight_commit(self):
        ticket = self.begin()
        self.store.clear(self.identity, self.chat.id, 0, str(uuid4()))
        with self.assertRaises(MemoryConflict):
            self.store.commit_turn(ticket, apply_operations(ticket.snapshot, []))
        self.assertEqual(self.store.read(self.identity, self.chat.id).facts, [])
        self.assertEqual(self.store.sources(self.identity, self.chat.id), [])

    def test_update_and_idempotent_replay(self):
        record = uuid4()
        ticket = self.begin(record)
        changes = apply_operations(ticket.snapshot, [Operation('add', entity='旅行', attribute='预算',
                                    value='3000', quote='预算3000', source=ticket.event_id)])
        first = self.store.commit_turn(ticket, changes)
        self.assertEqual(first.version, 1)
        replay = self.begin(record)
        self.assertEqual(replay.status, 'completed')
        self.assertEqual(replay.snapshot.facts[0]['value'], '3000')
        self.assertEqual(self.store.commit_turn(ticket, changes).version, 1)

    def test_wrong_identity_and_deleted_chat_denied(self):
        for identity in (Identity(str(self.app.id), 'other', 'CHAT_USER'),
                         Identity(str(self.app.id), 'owner', 'ANONYMOUS_USER')):
            with self.assertRaises(MemoryDenied):
                self.store.read(identity, self.chat.id)
        self.chat.is_deleted = True
        self.chat.save()
        with self.assertRaises(MemoryDenied):
            self.store.read(self.identity, self.chat.id)

    def test_correction_and_clear_version_checks(self):
        ticket = self.begin()
        first = self.store.commit_turn(ticket, apply_operations(ticket.snapshot, [Operation('add', entity='旅行',
                          attribute='预算', value='3000', quote='预算3000', source=ticket.event_id)]))
        corrected = self.store.correct(self.identity, self.chat.id, first.facts[0]['id'],
                                      Operation('replace', value='4000'), first.version, str(uuid4()))
        self.assertEqual(corrected.facts[0]['value'], '4000')
        with self.assertRaises(MemoryConflict):
            self.store.clear(self.identity, self.chat.id, first.version, str(uuid4()))
        request_id = str(uuid4())
        cleared = self.store.clear(self.identity, self.chat.id, corrected.version, request_id)
        self.assertEqual(self.store.clear(self.identity, self.chat.id, corrected.version, request_id), cleared)
        self.assertTrue(Chat.objects.filter(pk=self.chat.id).exists())
