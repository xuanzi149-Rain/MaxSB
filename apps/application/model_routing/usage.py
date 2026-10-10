# coding=utf-8
"""Provider usage is separate from tokenizer estimates."""


def summarize_attempts(attempts):
    result = {'model_call_count': len(attempts), 'usage_source': 'provider' if attempts else 'no_model_called'}
    for key in ('input_tokens', 'output_tokens'):
        values = [(attempt.get('usage') or {}).get(key) for attempt in attempts]
        result[key] = sum(values) if all(type(v) is int and v >= 0 for v in values) else None
    if any(result[k] is None for k in ('input_tokens', 'output_tokens')):
        result['usage_source'] = 'unknown'
    return result


def workflow_total(details, key):
    if any(row.get('model_routing') and row.get(key) is None for row in details.values()):
        return None
    return sum(row[key] for row in details.values() if row.get(key) is not None)
