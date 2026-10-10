# coding=utf-8
import re

DEFAULTS = {'enabled': False, 'context_token_budget': 2048, 'extraction_input_token_budget': 4096,
            'extraction_output_token_limit': 1024, 'extraction_timeout_seconds': 20}
RANGES = {'context_token_budget': (128, 32768), 'extraction_input_token_budget': (256, 32768),
          'extraction_output_token_limit': (128, 4096), 'extraction_timeout_seconds': (1, 60)}


def parse_memory_policy(data):
    if data is None:
        return dict(DEFAULTS)
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError('Invalid memory policy')
    result = {**DEFAULTS, **data}
    if not isinstance(result['enabled'], bool):
        raise ValueError('Memory enabled must be boolean')
    for key, (low, high) in RANGES.items():
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f'{key} must be between {low} and {high}')
    return result


def validate_node(data):
    policy = parse_memory_policy(data.get('memory_policy'))
    if not policy['enabled']:
        return
    if any(data.get(k) for k in ('tool_ids', 'mcp_servers', 'mcp_tool_id', 'mcp_tool_ids', 'application_ids',
                                 'skill_tool_ids', 'vision', 'image_list', 'video_list', 'audio_list', 'document_list')):
        raise ValueError('Conversation memory supports text nodes without tools only')
    if re.search(r'\{[^}]*\bmemory\b[^}]*\}', str(data.get('prompt', '')) + str(data.get('system', ''))):
        raise ValueError('Do not combine session memory with the upstream memory variable')


def validate_memory_workflow(workflow):
    enabled = []
    for node in workflow.nodes:
        data = node.properties.get('node_data') or {}
        if parse_memory_policy(data.get('memory_policy'))['enabled']:
            validate_node(data)
            if node.type != 'ai-chat-node':
                raise ValueError('Memory requires an AI text node')
            enabled.append(node)
    mode = getattr(workflow.workflow_mode, 'value', workflow.workflow_mode)
    if len(enabled) > 1 or (enabled and mode != 'application'):
        raise ValueError('Only one top-level application AI node may enable memory')
