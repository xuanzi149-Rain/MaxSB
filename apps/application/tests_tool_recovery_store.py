# coding=utf-8
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.test import TransactionTestCase
from django.db import close_old_connections
from uuid import uuid4
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from application.models import Application, ApplicationFolder, Chat
from application.tool_recovery.types import Identity, RecoveryConflict, RecoveryDenied
from application.tool_recovery.store import RecoveryStore


class RecoveryFixture(TestCase):
    def setUp(self):
        ApplicationFolder.objects.get_or_create(id='default', defaults={'name': 'default'})
        self.app = Application.objects.create(id=uuid4(), name='recovery', workspace_id='default')
        self.chat = Chat.objects.create(application=self.app, chat_user_id='owner', chat_user_type='CHAT_USER')
        self.identity = Identity(str(self.app.id), 'owner', 'CHAT_USER')
        self.store = RecoveryStore()
        self.run = self.store.create(self.identity, self.chat.id, uuid4(), {'fingerprint': 'v1', 'params': {}})
        self.claim = self.store.initial_claim(self.run)

    def fail_tool(self, mode='read_only'):
        step = self.store.begin_step(self.claim, 'tool', 'mcp-node')
        attempt = self.store.begin_attempt(self.claim, 'tool', {'a': 1}, {'mode': mode})
        self.store.finish_attempt(self.claim, attempt.id, 'failed', 'timeout')
        self.store.fail(self.claim, 'tool', 'failed', 'timeout')
        return step


class StoreTests(RecoveryFixture):
    def test_duplicate_resume_does_not_create_second_claim(self):
        self.fail_tool()
        self.run.refresh_from_db()
        request = str(uuid4())
        claim = self.store.claim(self.identity, self.run.id, request, self.run.version)
        duplicate = self.store.claim(self.identity, self.run.id, request, self.run.version)
        self.assertTrue(claim.acquired)
        self.assertFalse(duplicate.acquired)
        with self.assertRaises(RecoveryConflict):
            self.store.claim(self.identity, self.run.id, str(uuid4()), claim.generation)

    def test_stale_executor_cannot_checkpoint(self):
        self.fail_tool()
        self.run.refresh_from_db()
        self.store.claim(self.identity, self.run.id, str(uuid4()), self.run.version)
        with self.assertRaises(RecoveryConflict):
            self.store.checkpoint(self.claim, 'tool', {'result': 'late'}, {})

    def test_input_and_key_stay_stable(self):
        step = self.fail_tool()
        step.refresh_from_db()
        self.run.refresh_from_db()
        claim = self.store.claim(self.identity, self.run.id, str(uuid4()), self.run.version)
        retry = self.store.begin_attempt(claim, 'tool', {'a': 2}, {'mode': 'read_only'})
        self.assertEqual(retry.step.inputs, {'a': 1})
        self.assertEqual(retry.step.key, step.key)

    def test_unknown_cannot_resume(self):
        self.store.begin_step(self.claim, 'tool', 'mcp-node')
        self.store.fail(self.claim, 'tool', 'outcome_unknown', 'timeout')
        self.run.refresh_from_db()
        with self.assertRaises(RecoveryConflict):
            self.store.claim(self.identity, self.run.id, str(uuid4()), self.run.version)

    def test_cross_identity_and_deleted_denied(self):
        with self.assertRaises(RecoveryDenied):
            self.store.read(Identity(str(self.app.id), 'other', 'CHAT_USER'), self.run.id)
        self.chat.is_deleted = True
        self.chat.save()
        with self.assertRaises(RecoveryDenied):
            self.store.read(self.identity, self.run.id)

    def test_expired_claim_requires_fencing(self):
        self.store.begin_step(self.claim, 'tool', 'mcp-node')
        self.store.begin_attempt(self.claim, 'tool', {}, {'mode': 'unprotected_write'})
        self.run.lease_until = timezone.now() - timedelta(seconds=1)
        self.run.save(update_fields=['lease_until'])
        with self.assertRaises(RecoveryConflict):
            self.store.checkpoint(self.claim, 'tool', {}, {})
        with self.assertRaises(RecoveryConflict):
            self.store.claim(self.identity, self.run.id, str(uuid4()), self.run.version)
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, 'outcome_unknown')




class ConcurrentStoreTests(TransactionTestCase):
    setUp = RecoveryFixture.setUp
    fail_tool = RecoveryFixture.fail_tool

    def test_two_resume_requests_only_one_executor(self):
        self.fail_tool()
        self.run.refresh_from_db()
        barrier = Barrier(2)
        def resume():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                claim = RecoveryStore().claim(self.identity, self.run.id, str(uuid4()), self.run.version)
                return claim.acquired
            except RecoveryConflict:
                return False
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: resume(), range(2)))
        self.assertEqual(sorted(results), [False, True])


class ResolutionTests(RecoveryFixture):
    def test_confirmed_execution_returns_result_without_remote_call(self):
        from application.tool_recovery.executor import execute_mcp
        from application.tool_recovery.policy import RecoveryPolicy
        self.store.begin_step(self.claim, 'tool', 'mcp-node')
        self.store.begin_attempt(self.claim, 'tool', {}, {'mode': 'unprotected_write'})
        self.store.fail(self.claim, 'tool', 'outcome_unknown', 'timeout')
        self.run.refresh_from_db()
        self.store.resolve(self.run.id, 'manager', str(uuid4()), self.run.version, 'executed',
                           'remote audit operation 123 completed', ['receipt:123'])
        self.run.refresh_from_db()
        claim = self.store.claim(self.identity, self.run.id, str(uuid4()), self.run.version)
        result = execute_mcp(claim, 'tool', RecoveryPolicy.parse({}), None, '', '', {})
        self.assertEqual(result, ['receipt:123'])
        self.run.refresh_from_db()
        self.assertEqual(self.run.resolution[0]['actor'], 'manager')


class FinalPersistenceTests(RecoveryFixture):
    def test_stale_final_record_cannot_overwrite_recovered_answer(self):
        from application.models import ChatRecord
        from application.serializers.common import ChatInfo
        self.fail_tool()
        self.run.refresh_from_db()
        current = self.store.claim(self.identity, self.run.id, str(uuid4()), self.run.version)
        self.store.complete(current)
        info = ChatInfo(str(self.chat.id), 'owner', 'CHAT_USER', '', {}, [], [], str(self.app.id))
        record = ChatRecord(id=self.run.record_id, chat=self.chat, problem_text='q', answer_text='recovered',
                            details={}, answer_text_list=[], index=0)
        self.assertTrue(self.store.persist_record(current, info, record))
        record.answer_text = 'late old answer'
        self.assertFalse(self.store.persist_record(self.claim, info, record))
        self.assertEqual(ChatRecord.objects.get(id=record.id).answer_text, 'recovered')
        self.assertFalse(self.store.persist_record(current, info, record))

    def test_completed_checkpoints_can_publish_after_crash(self):
        from application.models import ChatRecord
        self.run.snapshot['node_ids'] = ['tool']
        self.run.snapshot['params']['question'] = 'q'
        self.run.save()
        self.store.begin_step(self.claim, 'tool', 'mcp-node')
        self.store.checkpoint(self.claim, 'tool', {'context': {'result': ['receipt']}, 'answer_text': 'receipt',
            'details': {'node_id': 'tool', 'runtime_node_id': 'runtime-tool', 'status': 200},
            'answers': [{'content': 'receipt'}]}, {'context': {}, 'chat_context': {}})
        self.run.lease_until = timezone.now() - timedelta(seconds=1)
        self.run.save(update_fields=['lease_until'])
        self.store.reconcile_expired(self.run.id)
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, 'succeeded')
        self.assertEqual(ChatRecord.objects.get(id=self.run.record_id).answer_text, 'receipt')


    def test_crash_between_nodes_resumes_next_without_repeating_write(self):
        self.run.snapshot['node_ids'] = ['a', 'b']
        self.run.snapshot['node_order'] = [{'id': 'a', 'type': 'mcp-node'}, {'id': 'b', 'type': 'mcp-node'}]
        self.run.save()
        self.store.begin_step(self.claim, 'a', 'mcp-node')
        self.store.checkpoint(self.claim, 'a', {'context': {'result': ['written']}}, {})
        self.run.lease_until = timezone.now() - timedelta(seconds=1)
        self.run.save(update_fields=['lease_until'])
        self.store.reconcile_expired(self.run.id)
        self.run.refresh_from_db()
        claim = self.store.claim(self.identity, self.run.id, str(uuid4()), self.run.version)
        self.assertTrue(claim.acquired)
        self.assertEqual(self.run.failed_node, 'b')
        self.assertEqual(self.run.steps.get(node_id='a').status, 'succeeded')
        self.assertEqual(self.run.steps.get(node_id='b').error_type, 'not_started')
