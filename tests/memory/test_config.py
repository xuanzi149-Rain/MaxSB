import unittest
from types import SimpleNamespace
from application.conversation_memory.config import parse_memory_policy, validate_memory_workflow


def node(**data):
    return SimpleNamespace(type='ai-chat-node', properties={'node_data': data})


class ConfigTests(unittest.TestCase):
    def test_missing_disabled(self):
        self.assertFalse(parse_memory_policy(None)['enabled'])

    def test_invalid_budget_rejected(self):
        with self.assertRaises(ValueError):
            parse_memory_policy({'enabled': True, 'context_token_budget': 0})

    def test_multiple_and_tool_nodes_rejected(self):
        for nodes in ([node(memory_policy={'enabled': True})] * 2,
                      [node(memory_policy={'enabled': True}, tool_ids=['tool'])],
                      [node(memory_policy={'enabled': True}, prompt='{{global.memory}}')]):
            with self.assertRaises(ValueError):
                validate_memory_workflow(SimpleNamespace(nodes=nodes, workflow_mode='application'))

    def test_other_mode_rejected(self):
        with self.assertRaises(ValueError):
            validate_memory_workflow(SimpleNamespace(nodes=[node(memory_policy={'enabled': True})],
                                                     workflow_mode='TOOL'))

    def test_nested_loop_memory_rejected_before_execution(self):
        loop = SimpleNamespace(type='loop-node', properties={'node_data': {'loop_body': {'nodes': [
            {'type': 'ai-chat-node', 'properties': {'node_data': {'memory_policy': {'enabled': True}}}}]}}})
        with self.assertRaises(ValueError):
            validate_memory_workflow(SimpleNamespace(nodes=[loop], workflow_mode='application'))
