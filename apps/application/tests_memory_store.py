# coding=utf-8
import time
from queue import Queue
from concurrent.futures import ThreadPoolExecutor
from django.test import TransactionTestCase
from django.db import close_old_connections, connection, transaction
from application.models import ConversationMemory
from uuid import uuid4
from django.test import TestCase
from application.models import Application, Chat
from application.conversation_memory.store import MemoryStore, MemoryConflict, MemoryDenied
from application.conversation_memory.types import Identity, Operation
from application.conversation_memory.policy import apply_operations


class MemoryFixture(TestCase):
    def setUp(self):
        self.app = Application.objects.create(id=uuid4(), name='memory', workspace_id='default')
        self.chat = Chat.objects.create(application=self.app, chat_user_id='owner', chat_user_type='CHAT_USER')
        self.identity = Identity(str(self.app.id), 'owner', 'CHAT_USER')
        self.store = MemoryStore()

    def begin(self, record=None):
        return self.store.begin_turn(self.identity, str(self.chat.id), str(record or uuid4()), '预算3000')


class StoreTests(MemoryFixture):
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

    def test_rechat_cannot_change_original_message(self):
        record = uuid4()
        self.begin(record)
        with self.assertRaises(MemoryConflict):
            self.store.begin_turn(self.identity, self.chat.id, str(record), '预算9000')

    def test_manual_correction_invalidates_old_ticket(self):
        first = self.begin()
        state = self.store.commit_turn(first, apply_operations(first.snapshot, [Operation('add', entity='旅行',
                           attribute='预算', value='3000', quote='预算3000', source=first.event_id)]))
        old = self.begin()
        self.store.correct(self.identity, self.chat.id, state.facts[0]['id'], Operation('replace', value='4000'),
                           state.version, str(uuid4()))
        with self.assertRaises(MemoryConflict):
            self.store.commit_turn(old, apply_operations(old.snapshot, []))
        self.assertEqual(self.store.read(self.identity, self.chat.id).facts[0]['value'], '4000')


    def test_clear_does_not_reextract_old_turn(self):
        record_id = str(uuid4())
        ticket = self.begin(record_id)
        self.store.commit_turn(ticket, apply_operations(ticket.snapshot, []))
        self.store.clear(self.identity, self.chat.id, 1, str(uuid4()))
        self.assertNotEqual(self.begin(record_id).status, 'received')


class MemoryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        from application.models.application import ApplicationFolder
        ApplicationFolder.objects.get_or_create(id='default', defaults={'name': 'Default'})

    def test_first_requests_share_one_state(self):
        app = Application.objects.create(id=uuid4(), name='concurrent memory', workspace_id='default')
        chat = Chat.objects.create(application=app, chat_user_id='owner', chat_user_type='CHAT_USER')
        identity = Identity(str(app.id), 'owner', 'CHAT_USER')
        def begin(_):
            close_old_connections()
            try:
                return MemoryStore().begin_turn(identity, str(chat.id), str(uuid4()), '预算3000').generation
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(list(executor.map(begin, [1, 2])), [0, 0])
        self.assertEqual(ConversationMemory.objects.filter(chat=chat).count(), 1)

    def test_correction_waits_for_extraction_commit_and_detects_conflict(self):
        app = Application.objects.create(id=uuid4(), name='race memory', workspace_id='default')
        chat = Chat.objects.create(application=app, chat_user_id='owner', chat_user_type='CHAT_USER')
        identity = Identity(str(app.id), 'owner', 'CHAT_USER')
        store = MemoryStore()
        ticket = store.begin_turn(identity, str(chat.id), str(uuid4()), '预算3000')
        initial = store.commit_turn(ticket, apply_operations(ticket.snapshot, [
            Operation('add', entity='旅行', attribute='预算', value='3000')]))
        ticket = store.begin_turn(identity, str(chat.id), str(uuid4()), '人数2')
        changes = apply_operations(ticket.snapshot, [Operation('add', entity='旅行', attribute='人数', value='2')])
        pid = Queue()
        def correct():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pid.put(cursor.fetchone()[0])
                try:
                    store.correct(identity, chat.id, initial.facts[0]['id'], Operation('replace', value='4000'),
                                  initial.version, str(uuid4()))
                    return 'overwritten'
                except MemoryConflict:
                    return 'conflict'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                ConversationMemory.objects.select_for_update().get(chat=chat)
                future = executor.submit(correct)
                backend_pid = pid.get(timeout=5)
                deadline = time.monotonic() + 5
                while True:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s', [backend_pid])
                        waiting = cursor.fetchone()
                    if waiting and waiting[0] == 'Lock':
                        break
                    if time.monotonic() > deadline:
                        raise AssertionError('Concurrent writer did not reach the locked state')
                    time.sleep(0.01)
                store.commit_turn(ticket, changes)
            self.assertEqual(future.result(timeout=5), 'conflict')
        self.assertEqual({f['value'] for f in store.read(identity, chat.id).facts}, {'3000', '2'})

    def test_migration_round_trip(self):
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        executor.migrate([('application', '0015_application_default_model_setting_and_more')])
        self.assertNotIn('application_conversation_memory', connection.introspection.table_names())
        executor = MigrationExecutor(connection)
        executor.migrate([('application', '0016_conversation_memory')])
        self.assertIn('application_conversation_memory_event', connection.introspection.table_names())
