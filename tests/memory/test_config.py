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

    def test_multiple_and_legacy_memory_rejected(self):
        for nodes in ([node(memory_policy={'enabled': True})] * 2,
                      [node(memory_policy={'enabled': True}, prompt='{{global.memory}}')]):
            with self.assertRaises(ValueError):
                validate_memory_workflow(SimpleNamespace(nodes=nodes, workflow_mode='application'))

    def test_other_mode_rejected(self):
        with self.assertRaises(ValueError):
            validate_memory_workflow(SimpleNamespace(nodes=[node(memory_policy={'enabled': True})],
                                                     workflow_mode='TOOL'))

    def test_single_nested_loop_memory_allowed(self):
        loop = SimpleNamespace(type='loop-node', properties={'node_data': {'loop_body': {'nodes': [
            {'type': 'ai-chat-node', 'properties': {'node_data': {'memory_policy': {'enabled': True}}}}]}}})
        validate_memory_workflow(SimpleNamespace(nodes=[loop], workflow_mode='application'))
        with self.assertRaises(ValueError):
            validate_memory_workflow(SimpleNamespace(nodes=[loop, node(memory_policy={'enabled': True})],
                                                     workflow_mode='application'))

    def test_tool_and_multimodal_nodes_allowed_in_application_loop(self):
        validate_memory_workflow(SimpleNamespace(nodes=[node(memory_policy={'enabled': True},
            tool_ids=['tool'], vision=True, image_list=['image'])], workflow_mode='application-loop'))
