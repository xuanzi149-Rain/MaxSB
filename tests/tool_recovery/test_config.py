import unittest
from types import SimpleNamespace as NS
from application.tool_recovery.config import validate_recovery_workflow


def flow(enabled=True):
    nodes = [NS(id='start-node', type='start-node', properties={'node_data': {'tool_recovery': enabled}}),
             NS(id='mcp', type='mcp-node', properties={'node_data': {}})]
    return NS(nodes=nodes, edges=[NS(sourceNodeId='start-node', targetNodeId='mcp')], workflow_mode='application')


class ConfigTests(unittest.TestCase):
    def test_serial_graph_allowed(self):
        self.assertTrue(validate_recovery_workflow(flow()))

    def test_disabled_does_not_restrict_existing_graph(self):
        f = flow(False)
        f.nodes[1].type = 'loop-node'
        self.assertFalse(validate_recovery_workflow(f))

    def test_branch_cycle_or_disconnected_rejected(self):
        for mode in ('branch', 'cycle', 'disconnected'):
            f = flow()
            if mode == 'branch':
                f.nodes.append(NS(id='m2', type='mcp-node', properties={'node_data': {}}))
                f.edges.append(NS(sourceNodeId='start-node', targetNodeId='m2'))
            elif mode == 'cycle':
                f.edges.append(NS(sourceNodeId='mcp', targetNodeId='start-node'))
            else:
                f.edges = []
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_recovery_workflow(f)

    def test_tools_in_ai_and_exception_branches_rejected(self):
        f = flow()
        f.nodes[1].properties['enableException'] = True
        with self.assertRaises(ValueError):
            validate_recovery_workflow(f)
        f.nodes[1].properties = {'node_data': {'tools': ['tool']}}
        f.nodes[1].type = 'ai-chat-node'
        with self.assertRaises(ValueError):
            validate_recovery_workflow(f)
