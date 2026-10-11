# coding=utf-8
"""Read actual provider usage from transient LangChain traces; never export prompts or credentials."""


def extract_usage(runs) -> dict:
    usages, seen, model_calls = [], set(), []
    def field(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
    def visit(run):
        identity = field(run, 'id')
        if identity and str(identity) in seen:
            return
        if identity:
            seen.add(str(identity))
        if field(run, 'run_type') == 'llm':
            outputs = field(run, 'outputs') or {}
            usage = None
            for generation in outputs.get('generations', []):
                for item in generation:
                    message = item.get('message') or {}
                    payload = message.get('kwargs', message.get('data', message))
                    usage = payload.get('usage_metadata') or usage
            usage = usage or (outputs.get('llm_output') or {}).get('token_usage')
            if usage:
                inputs = usage.get('input_tokens', usage.get('prompt_tokens'))
                outputs_count = usage.get('output_tokens', usage.get('completion_tokens'))
                usages.append((inputs, outputs_count))
            else:
                usages.append((None, None))
            metadata = (field(run, 'extra') or {}).get('metadata') or {}
            model_calls.append({'attempt_id': str(identity) if identity else None,
                'model_id': metadata.get('routing_model_id'), 'role': metadata.get('routing_role'),
                'input_tokens': usages[-1][0], 'output_tokens': usages[-1][1],
                'status': 'failed' if field(run, 'error') else 'completed'})
        for child in field(run, 'child_runs', []):
            visit(child)
    for run in runs:
        visit(run)
    known = bool(usages) and all(type(n) is int and n >= 0 for pair in usages for n in pair)
    return {'input_tokens': sum(p[0] for p in usages) if known else None,
            'output_tokens': sum(p[1] for p in usages) if known else None,
            'usage_source': 'provider_callback' if known else 'unknown', 'model_call_count': len(usages), 'model_calls': model_calls}
