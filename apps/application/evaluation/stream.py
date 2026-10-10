# coding=utf-8
"""Incremental MaxKB SSE decoding. Frame usage is cumulative, never additive."""
import codecs
import json


def aggregate_stream(chunks) -> dict:
    decoder = codecs.getincrementaldecoder('utf-8')()
    buffer = ''
    result = {'answer': '', 'complete': False, 'input_tokens': None, 'output_tokens': None,
              'usage_source': 'unknown', 'record_id': None, 'error': None}

    def frame(raw):
        data = '\n'.join(line[5:].lstrip() for line in raw.split('\n') if line.startswith('data:'))
        if not data or data == '[DONE]':
            return
        value = json.loads(data)
        result['answer'] += value.get('content') or ''
        result['record_id'] = value.get('chat_record_id', result['record_id'])
        if value.get('code', 200) not in (0, 200) or value.get('error') or value.get('node_status') == 'ERROR':
            result['error'] = 'chat_response_error'
        # Node-end frames are not necessarily the final conversation frame.
        if value.get('is_end'):
            result['complete'] = True
            usage = value.get('usage') or {}
            inputs, outputs = usage.get('prompt_tokens'), usage.get('completion_tokens')
            if all(type(n) is int and n >= 0 for n in (inputs, outputs)) and inputs + outputs > 0:
                result.update(input_tokens=inputs, output_tokens=outputs, usage_source='maxkb_reported')
    for chunk in chunks:
        buffer += decoder.decode(chunk) if isinstance(chunk, bytes) else chunk
        # Normalize only after a full CRLF is available; a trailing CR stays buffered.
        buffer = buffer.replace('\r\n', '\n')
        while '\n\n' in buffer:
            raw, buffer = buffer.split('\n\n', 1)
            frame(raw)
    buffer += decoder.decode(b'', final=True)
    if buffer.strip():
        result['error'] = 'truncated_stream'
        result['complete'] = False
    if not result['complete']:
        result.update(input_tokens=None, output_tokens=None, usage_source='unknown')
        result['error'] = result['error'] or 'missing_end_frame'
    if result['error']:
        result['answer'] = ''
    return result
