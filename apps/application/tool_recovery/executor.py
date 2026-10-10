# coding=utf-8
"""One recorded MCP attempt at a time; cancellation is not remote rollback."""
import asyncio
import time
from dataclasses import asdict
from .policy import classify_error, can_retry, failure_status
from .store import RecoveryStore


class ToolExecutionFailure(Exception):
    def __init__(self, status, error_type):
        super().__init__(f'Tool execution {status}: {error_type}')
        self.status, self.error_type = status, error_type


def execute_mcp(claim, node_id, policy, backend, server, tool, arguments):
    store = RecoveryStore()
    from application.models import ToolStep
    step = ToolStep.objects.get(run_id=claim.run_id, node_id=node_id)
    if 'confirmed_result' in step.output:
        return step.output['confirmed_result']
    if policy.mode == 'idempotent_write':
        schema = asyncio.run(asyncio.wait_for(backend.describe_tool(server, tool), policy.timeout))
        if schema.get('properties', {}).get(policy.key_field, {}).get('type') != 'string':
            raise ValueError('Tool does not expose the required string idempotency parameter')
    for number in range(1, policy.retries + 2):
        store.heartbeat(claim)
        attempt = store.begin_attempt(claim, node_id, arguments, asdict(policy))
        params = dict(attempt.step.inputs)
        if policy.mode == 'idempotent_write':
            params[policy.key_field] = str(attempt.step.key)
        try:
            res = asyncio.run(asyncio.wait_for(backend.call_tool(server, tool, params), policy.timeout))
            kind = 'business' if res.isError else ''
            result = [c.text for c in res.content if hasattr(c, 'text')]
        except Exception as exc:
            kind = classify_error(exc)
            result = None
        if not kind:
            store.finish_attempt(claim, attempt.id, 'succeeded')
            return result
        retry = can_retry(policy, kind, number)
        wait = min(0.5 * 2 ** (number - 1), 8) if retry else 0
        state = failure_status(policy, kind)
        store.finish_attempt(claim, attempt.id, state, kind, wait)
        if not retry:
            raise ToolExecutionFailure(state, kind)
        time.sleep(wait)
    raise AssertionError('Unreachable retry state')
