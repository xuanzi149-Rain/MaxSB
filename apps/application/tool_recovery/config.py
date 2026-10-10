# coding=utf-8
from .policy import RecoveryPolicy


def validate_recovery_workflow(workflow):
    starts = [n for n in workflow.nodes if n.type == 'start-node']
    enabled = any(n.properties.get('node_data', {}).get('tool_recovery', False) for n in starts)
    if not enabled:
        return False
    if len(starts) != 1 or getattr(workflow.workflow_mode, 'value', workflow.workflow_mode) != 'application':
        raise ValueError('Recovery requires a serial application workflow')
    incoming, outgoing = {}, {}
    for node in workflow.nodes:
        if node.type == 'base-node':
            continue
        if node.type not in {'start-node', 'mcp-node', 'ai-chat-node'} or node.properties.get('enableException'):
            raise ValueError('Unsupported recovery node or exception branch')
        data = node.properties.get('node_data') or {}
        if node.type == 'mcp-node':
            RecoveryPolicy.parse(data.get('recovery_policy'))
        if node.type == 'ai-chat-node' and any(data.get(k) for k in (
                'tools', 'tool_ids', 'application_ids', 'application_enable', 'tool_enable', 'mcp_enable', 'mcp_tool_id', 'mcp_tool_ids', 'mcp_servers', 'skill_tool_ids',
                'image_list', 'audio_list', 'video_list', 'document_list', 'other_list')):
            raise ValueError('Recovery AI nodes must be text only and have no tools')
    for edge in workflow.edges:
        outgoing.setdefault(edge.sourceNodeId, []).append(edge.targetNodeId)
        incoming.setdefault(edge.targetNodeId, []).append(edge.sourceNodeId)
    if any(len(v) > 1 for v in [*incoming.values(), *outgoing.values()]):
        raise ValueError('Recovery does not support branches')
    seen, current = set(), starts[0].id
    while current is not None:
        if current in seen:
            raise ValueError('Recovery does not support cycles')
        seen.add(current)
        current = next(iter(outgoing.get(current, [])), None)
    if seen != {n.id for n in workflow.nodes if n.type != 'base-node'}:
        raise ValueError('Recovery graph contains disconnected nodes')
    return True
