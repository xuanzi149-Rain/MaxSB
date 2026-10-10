# coding=utf-8
"""Result allowlist: raw node inputs, credentials and exception messages are not exported."""
import re

PUBLIC_FIELDS = {'answer', 'case_id', 'status', 'trace', 'node_id', 'node_type', 'run_time', 'elapsed_seconds',
                 'input_tokens', 'output_tokens', 'usage_source', 'error', 'complete', 'record_id',
                 'retrieved_evidence_ids', 'citations', 'evidence_id', 'document_name', 'paragraph_id',
                 'tracking_id', 'chat_id', 'estimated_input_tokens', 'estimated_output_tokens', 'model_call_count', 'evaluation_scope',
                 'score', 'review', 'actual_cost', 'currency', 'turns', 'tool_events', 'read_only', 'outcome', 'model_calls', 'model_routing', 'task_id', 'attempts', 'attempt_id',
                 'model_id', 'model_name', 'response_model', 'role', 'selected_role', 'rule_id', 'rule_version', 'reason',
                 'upgrade_reason', 'started_at', 'ended_at', 'usage', 'cache_read_tokens',
                 'priced_cost', 'price_basis', 'price_version', 'price_source'}


def sanitize_result(result):
    if isinstance(result, dict):
        clean = {key: sanitize_result(value) for key, value in result.items() if key in PUBLIC_FIELDS}
        if clean.get('error'):
            clean['answer'] = ''
            if not re.fullmatch(r'[A-Za-z_]{1,80}', str(clean['error'])):
                clean['error'] = 'execution_error'
        return clean
    if isinstance(result, list):
        return [sanitize_result(value) for value in result]
    return result
