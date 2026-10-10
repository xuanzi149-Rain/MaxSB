# coding=utf-8
import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from application.tests_tool_recovery_store import RecoveryFixture
from application.tool_recovery.executor import execute_mcp
from application.tool_recovery.policy import RecoveryPolicy
from application.flow.backend.sandbox_mcp import SandboxMCPBackend, CONFIG


class TransportTests(RecoveryFixture):
    def test_actual_mcp_response_loss_has_one_remote_write(self):
        self.check_transport(0)

    def test_sandbox_denies_loopback_without_remote_side_effect(self):
        self.check_transport(1)

    def check_transport(self, sandbox):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        server_file = Path(__file__).resolve().parents[2] / 'tests/tool_recovery/fault_server.py'
        process = subprocess.Popen([sys.executable, str(server_file), str(port), '20' if sandbox else '3'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            config_get = CONFIG.get
            with patch.object(CONFIG, 'get', side_effect=lambda k, *a: sandbox if k == 'SANDBOX' else config_get(k, *a)):
                backend = SandboxMCPBackend({'local': {'transport': 'streamable_http',
                                                      'url': f'http://127.0.0.1:{port}/mcp'}})
                self.store.begin_step(self.claim, 'tool', 'mcp-node')
                policy = RecoveryPolicy.parse({'mode': 'idempotent_write', 'key_field': 'request_id',
                                               'timeout': 15 if sandbox else 2})
                if sandbox:
                    with self.assertRaises(ExceptionGroup):
                        execute_mcp(self.claim, 'tool', policy, backend, 'local', 'write_once', {})
                    self.assertEqual(self.run.steps.get().attempts.count(), 0)
                    # Observe the fixture outside the sandbox; never weaken its network policy.
                    with patch.object(CONFIG, 'get', side_effect=lambda k, *a: 0 if k == 'SANDBOX' else config_get(k, *a)):
                        observer = SandboxMCPBackend({'local': {'transport': 'streamable_http',
                                                              'url': f'http://127.0.0.1:{port}/mcp'}})
                        actual = json.loads(asyncio.run(observer.call_tool('local', 'stats', {})).content[0].text)
                    self.assertEqual(actual['writes'], 0)
                    self.assertEqual(actual['calls'], 0)
                else:
                    output = execute_mcp(self.claim, 'tool', policy, backend, 'local', 'write_once', {})
                    self.assertEqual(json.loads(output[0])['receipt'], 1)
                    result = asyncio.run(backend.call_tool('local', 'stats', {}))
                    actual = json.loads(result.content[0].text)
                    self.assertEqual(actual['writes'], 1)
                    self.assertEqual(actual['calls'], 2)
                    self.assertEqual(len(actual['keys']), 1)
        finally:
            process.terminate()
            process.wait(timeout=5)
