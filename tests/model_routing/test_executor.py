import asyncio
import unittest
from types import SimpleNamespace
from application.model_routing.executor import execute_routed
from application.model_routing.usage import summarize_attempts
from application.model_routing.types import RoutingError
from application.model_routing.config import parse_policy
from application.model_routing.policy import select_route
from test_core import config


def chunk(text, usage=None):
    return SimpleNamespace(content=text, additional_kwargs={}, usage_metadata=usage)


class Model:
    def __init__(self, items, calls):
        self.items, self.calls = items, calls

    async def astream(self, messages, **kwargs):
        self.calls.append(messages)
        for item in self.items:
            if item == 'wait':
                await asyncio.sleep(10)
            elif isinstance(item, Exception):
                raise item
            else:
                yield item


class ExecutorTests(unittest.TestCase):
    def run_case(self, low, high, cancelled=lambda: False, policy=None):
        policy = policy or parse_policy(config())
        calls, trace = [], {}
        models = {'low': Model(low, calls), 'high': Model(high, calls)}
        output = execute_routed(['frozen'], policy,
            select_route('提取姓名', policy, has_history=False, has_tool_results=False),
            model_factory=lambda role: models[role], evidence_ids=frozenset(), cancelled=cancelled, trace=trace)
        return output, calls, trace

    def test_failed_draft_never_escapes_and_two_attempts_count(self):
        output, calls, trace = self.run_case(
            [chunk('bad', {'input_tokens': 10, 'output_tokens': 2})],
            [chunk('{"name":"A"}', {'input_tokens': 20, 'output_tokens': 4})])
        self.assertEqual(''.join(c.content for c in output), '{"name":"A"}')
        self.assertEqual(calls, [['frozen'], ['frozen']])
        self.assertEqual(len(trace['attempts']), 2)
        self.assertEqual(trace['usage']['input_tokens'], 30)
        self.assertEqual(trace['usage']['output_tokens'], 6)
        self.assertEqual(trace['attempts'][0]['error'], 'invalid_json')

    def test_double_failure_and_cancel(self):
        output, calls, trace = self.run_case([chunk('bad')], [chunk('bad again')])
        with self.assertRaises(RoutingError):
            list(output)
        self.assertEqual(len(calls), 2)
        self.assertEqual(trace['status'], 'failed')
        self.assertIsNone(trace['usage']['input_tokens'])
        output, calls, trace = self.run_case([chunk('bad')], [], cancelled=lambda: True)
        with self.assertRaises(RoutingError):
            list(output)
        self.assertEqual(calls, [])
        self.assertEqual(trace['status'], 'cancelled')

    def test_timeout_upgrades_and_unknown_error_does_not(self):
        output, calls, trace = self.run_case(['wait'], [chunk('{"name":"A"}')],
                                             policy=parse_policy(config(timeout=1)))
        self.assertEqual(''.join(c.content for c in output), '{"name":"A"}')
        self.assertEqual(len(calls), 2)
        self.assertEqual(trace['attempts'][0]['error'], 'timeout')
        output, calls, trace = self.run_case([ValueError('secret')], [chunk('{"name":"A"}')])
        with self.assertRaises(RoutingError):
            list(output)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('secret', str(trace))

    def test_oversize_does_not_leak_or_retry(self):
        output, calls, trace = self.run_case([chunk('x' * 1048577)], [])
        with self.assertRaises(RoutingError):
            list(output)
        self.assertEqual(len(calls), 1)
        self.assertEqual(trace['attempts'][0]['error'], 'buffer_limit')

    def test_unknown_propagates_per_field(self):
        totals = summarize_attempts([{'usage': {'input_tokens': 3, 'output_tokens': 2}},
                                     {'usage': {'input_tokens': 4, 'output_tokens': None}}])
        self.assertEqual(totals['input_tokens'], 7)
        self.assertIsNone(totals['output_tokens'])

    def test_fixed_low_baseline_never_upgrades(self):
        policy = parse_policy(config())
        calls, trace, roles = [], {}, []
        low = Model([chunk('invalid')], calls)
        output = execute_routed([], policy,
            select_route('提取姓名', policy, has_history=False, has_tool_results=False),
            model_factory=lambda role: roles.append(role) or low, evidence_ids=frozenset(), cancelled=lambda: False,
            trace=trace, allow_upgrade=False)
        with self.assertRaises(RoutingError):
            list(output)
        self.assertEqual(len(calls), 1)
        self.assertEqual(roles, ['low'])
        self.assertEqual(trace['attempts'][0]['role'], 'low')

    def test_workflow_total_does_not_hide_unknown_routed_usage(self):
        from application.model_routing.usage import workflow_total
        self.assertIsNone(workflow_total({'ai': {'model_routing': {'attempts': [{}]}, 'message_tokens': None},
                                         'other': {'message_tokens': 20}}, 'message_tokens'))
        self.assertEqual(workflow_total({'old': {'message_tokens': 4}}, 'message_tokens'), 4)

    def test_cancellation_during_stream_hides_draft_and_does_not_upgrade(self):
        state = {'cancelled': False}
        calls, trace = [], {}
        class CancellingModel:
            async def astream(self, messages, **kwargs):
                calls.append(messages)
                yield chunk('{"name":')
                state['cancelled'] = True
                await asyncio.sleep(10)
        policy = parse_policy(config())
        result = execute_routed([], policy,
            select_route('提取姓名', policy, has_history=False, has_tool_results=False),
            model_factory=lambda role: CancellingModel(), evidence_ids=frozenset(),
            cancelled=lambda: state['cancelled'], trace=trace)
        with self.assertRaises(RoutingError):
            list(result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(trace['status'], 'cancelled')
