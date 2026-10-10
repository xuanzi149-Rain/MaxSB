# coding=utf-8
"""Conservative prepaid reservation for explicitly budgeted evaluation subprocesses."""
import fcntl
import json
import os
from decimal import Decimal
from pathlib import Path


def reserve_request(path, body):
    if body.get('model') != 'qwen3.7-plus' or body.get('enable_thinking') is not False:
        raise ValueError('budget_model_not_allowed')
    maximum = body.get('max_tokens', body.get('max_completion_tokens'))
    if not isinstance(maximum, int) or not 1 <= maximum <= 2048 or body.get('tools'):
        raise ValueError('budget_output_not_bounded')
    # UTF-8 bytes overbound text tokens; include generous chat framing allowance.
    input_bound = len(json.dumps(body, ensure_ascii=False).encode()) + 4096
    if input_bound > 65536:
        raise ValueError('budget_input_not_bounded')
    # Higher than Beijing list prices: 3 CNY/M input and 12 CNY/M output.
    reservation = (Decimal(input_bound) * 3 + Decimal(maximum) * 12) / 1000000
    with Path(path).open('r+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        ledger = json.load(handle)
        total = Decimal(ledger['reserved_cny']) + reservation
        if total > Decimal(ledger['limit_cny']):
            raise ValueError('evaluation_budget_exhausted')
        ledger.update(reserved_cny=str(total), requests=ledger['requests'] + 1)
        handle.seek(0)
        json.dump(ledger, handle)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())


def install_budget_guard():
    path = os.environ.get('MAXSB_EVALUATION_BUDGET_FILE')
    if not path:
        return
    import httpx
    original = httpx.Client.send

    def guarded(client, request, **kwargs):
        if request.url.host not in ('localhost', '127.0.0.1'):
            if request.url.host != 'token-plan.cn-beijing.maas.aliyuncs.com' or not request.url.path.endswith('/chat/completions'):
                raise ValueError('budget_endpoint_not_allowed')
            body = json.loads(request.content)
            try:
                reserve_request(path, body)
            except Exception as exc:
                # Only fixed guard reason codes and parameter shape; never prompts/headers.
                reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                Path(path + '.denied').write_text(json.dumps({'reason': reason,
                    'model': body.get('model'), 'max_tokens': body.get('max_tokens'),
                    'max_completion_tokens': body.get('max_completion_tokens'),
                    'enable_thinking': body.get('enable_thinking')}))
                raise
        return original(client, request, **kwargs)

    httpx.Client.send = guarded
