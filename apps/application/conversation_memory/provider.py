# coding=utf-8
"""Bounded native SDK extraction; no fallback to an unbounded invoke call."""


def provider_client(model):
    client = getattr(model, 'root_client', None)
    if client is not None and hasattr(client, 'with_options'):
        return 'openai', client
    client = getattr(model, '_client', None)
    if client is not None and hasattr(client, 'messages') and hasattr(client, 'with_options'):
        return 'anthropic', client
    return None, None


def extract_json(model, provider, client, instructions, content, limits):
    bounded = client.with_options(timeout=limits['extraction_timeout_seconds'], max_retries=0)
    common = {'model': getattr(model, 'model_name', None) or getattr(model, 'model', None),
              'max_tokens': limits['extraction_output_token_limit'], 'temperature': 0, 'stream': False}
    if provider == 'anthropic':
        response = bounded.messages.create(**common, system=instructions,
            messages=[{'role': 'user', 'content': content}], thinking={'type': 'disabled'})
        text = ''.join(block.text for block in response.content if block.type == 'text')
        usage = getattr(response, 'usage', None)
        return text, {'input_tokens': getattr(usage, 'input_tokens', None),
                      'output_tokens': getattr(usage, 'output_tokens', None)}
    response = bounded.chat.completions.create(**common,
        messages=[{'role': 'system', 'content': instructions}, {'role': 'user', 'content': content}],
        extra_body={'enable_thinking': False} if 'enable_thinking' in (getattr(model, 'extra_body', None) or {}) else None)
    usage = getattr(response, 'usage', None)
    return response.choices[0].message.content or '', {
        'input_tokens': getattr(usage, 'prompt_tokens', None),
        'output_tokens': getattr(usage, 'completion_tokens', None)}
