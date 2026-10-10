# coding=utf-8
import json
import os
import time
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace as NS
from application.tests_tool_recovery_store import RecoveryFixture
from application.tests_tool_recovery_executor import FaultBackend
from application.tool_recovery.executor import execute_mcp, ToolExecutionFailure
from application.tool_recovery.policy import RecoveryPolicy


class FaultReportTests(RecoveryFixture):
    def test_controlled_failure_matrix(self):
        class ReadBackend(FaultBackend):
            async def call_tool(self, server, tool, arguments):
                self.calls += 1
                if self.mode == 'transient' and self.calls == 1:
                    raise ConnectionResetError()
                return NS(isError=False, content=[NS(text='done')])
        rows = []
        for name, mode, backend in (
                ('success', 'read_only', ReadBackend('success')),
                ('transient', 'read_only', ReadBackend('transient')),
                ('business_failure', 'read_only', FaultBackend('business')),
                ('write_response_lost', 'idempotent_write', FaultBackend('lost')),
                ('unknown_write', 'unprotected_write', FaultBackend('timeout'))):
            self.store.begin_step(self.claim, name, 'mcp-node')
            started = time.monotonic()
            status, failure = 'succeeded', ''
            try:
                execute_mcp(self.claim, name, RecoveryPolicy.parse({'mode': mode, 'key_field': 'request_id'}),
                            backend, 'server', 'tool', {})
            except ToolExecutionFailure as exc:
                status, failure = exc.status, exc.error_type
            rows.append({'scenario': name, 'status': status, 'error_type': failure, 'calls': backend.calls,
                         'writes': len(backend.writes), 'duplicates': max(0, len(backend.writes) - 1),
                         'seconds': time.monotonic() - started, 'cost': None})
        self.assertEqual([r['status'] for r in rows], ['succeeded', 'succeeded', 'failed',
                                                    'succeeded', 'outcome_unknown'])
        self.assertEqual(rows[3]['writes'], 1)
        self.assertEqual(rows[4]['calls'], 1)
        run = self.store.create(self.identity, self.chat.id, uuid4(), {'params': {}})
        claim = self.store.initial_claim(run)
        self.store.begin_step(claim, 'manual', 'mcp-node')
        policy = RecoveryPolicy.parse({'mode': 'read_only', 'retries': 0})
        try:
            execute_mcp(claim, 'manual', policy, FaultBackend('timeout'), 's', 't', {})
        except ToolExecutionFailure as exc:
            self.store.fail(claim, 'manual', exc.status, exc.error_type)
        run.refresh_from_db()
        started = time.monotonic()
        resumed = self.store.claim(self.identity, run.id, str(uuid4()), run.version)
        output = execute_mcp(resumed, 'manual', policy, ReadBackend('success'), 's', 't', {})
        self.store.checkpoint(resumed, 'manual', {'context': {'result': output}}, {})
        seconds = time.monotonic() - started
        rows.append({'scenario': 'manual_timeout_resume', 'status': 'succeeded', 'error_type': '',
                     'calls': 2, 'writes': 0, 'duplicates': 0, 'seconds': seconds,
                     'resume_seconds': seconds, 'cost': None})
        if os.environ.get('TASK5_FAULT_OUTPUT'):
            Path(os.environ['TASK5_FAULT_OUTPUT']).write_text(json.dumps(rows, indent=2))
