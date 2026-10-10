# coding=utf-8
from types import SimpleNamespace as NS
from unittest.mock import patch
from application.tests_tool_recovery_store import RecoveryFixture
from application.tool_recovery.executor import execute_mcp, ToolExecutionFailure
from application.tool_recovery.policy import RecoveryPolicy


class FaultBackend:
    def __init__(self, mode):
        self.mode, self.calls, self.writes, self.keys = mode, 0, {}, []

    async def describe_tool(self, server, tool):
        return {'type': 'object', 'properties': {'request_id': {'type': 'string'}}}

    async def call_tool(self, server, tool, arguments):
        self.calls += 1
        if self.mode == 'business':
            return NS(isError=True, content=[NS(text='declined')])
        if self.mode == 'lost':
            key = arguments['request_id']
            self.keys.append(key)
            self.writes.setdefault(key, len(self.writes) + 1)
            if self.calls == 1:
                raise TimeoutError()
            return NS(isError=False, content=[NS(text=str(self.writes[key]))])
        raise TimeoutError()


class ExecutorTests(RecoveryFixture):
    def execute(self, backend, mode):
        self.store.begin_step(self.claim, 'tool', 'mcp-node')
        policy = RecoveryPolicy.parse({'mode': mode, 'key_field': 'request_id'})
        with patch('application.tool_recovery.executor.time.sleep'):
            return execute_mcp(self.claim, 'tool', policy, backend, 'server', 'write', {'a': 1})

    def test_retry_limit(self):
        backend = FaultBackend('timeout')
        with self.assertRaises(ToolExecutionFailure):
            self.execute(backend, 'read_only')
        self.assertEqual(backend.calls, 3)
        self.assertEqual(self.run.steps.get().attempts.count(), 3)

    def test_business_failure_is_not_success_or_retry(self):
        backend = FaultBackend('business')
        with self.assertRaises(ToolExecutionFailure) as failure:
            self.execute(backend, 'read_only')
        self.assertEqual(failure.exception.error_type, 'business')
        self.assertEqual(backend.calls, 1)

    def test_lost_response_keeps_key_and_one_write(self):
        backend = FaultBackend('lost')
        result = self.execute(backend, 'idempotent_write')
        self.assertEqual(result, ['1'])
        self.assertEqual(len(backend.writes), 1)
        self.assertEqual(backend.keys[0], backend.keys[1])

    def test_unknown_write_never_retries(self):
        backend = FaultBackend('timeout')
        with self.assertRaises(ToolExecutionFailure) as failure:
            self.execute(backend, 'unprotected_write')
        self.assertEqual(failure.exception.status, 'outcome_unknown')
        self.assertEqual(backend.calls, 1)

    def test_sdk_timeout_is_classified_without_message_matching(self):
        import httpx
        from application.tool_recovery.policy import classify_error
        self.assertEqual(classify_error(httpx.ReadTimeout('response lost')), 'timeout')
        self.assertEqual(classify_error(httpx.ConnectError('connection refused')), 'transient')

    def test_real_deadline_stops_waiting(self):
        import asyncio
        import time
        class SlowBackend(FaultBackend):
            async def call_tool(self, server, tool, arguments):
                self.calls += 1
                await asyncio.sleep(30)
        backend = SlowBackend('slow')
        self.store.begin_step(self.claim, 'tool', 'mcp-node')
        started = time.monotonic()
        with self.assertRaises(ToolExecutionFailure):
            execute_mcp(self.claim, 'tool', RecoveryPolicy.parse({'timeout': 1, 'retries': 0, 'mode': 'read_only'}),
                        backend, 's', 't', {})
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(backend.calls, 1)
