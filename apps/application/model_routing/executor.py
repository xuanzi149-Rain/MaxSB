# coding=utf-8
"""Cancellable async streams, bridged without background request threads."""
import asyncio
import copy
import time
from datetime import datetime, timezone
from uuid import uuid4
from .types import RoutingError
from .usage import summarize_attempts
from .validation import validate_output


def error_code(exc):
    if isinstance(exc, RoutingError):
        return str(exc)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return 'timeout'
    # Do not classify arbitrary exception strings or subclass names.
    try:
        import openai
        if isinstance(exc, openai.APITimeoutError):
            return 'timeout'
        if isinstance(exc, openai.APIConnectionError):
            return 'transport_error'
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return 'authorization_error'
    except ImportError:
        pass
    return 'execution_error'


async def next_chunk(iterator, deadline, cancelled):
    task = asyncio.create_task(iterator.__anext__())
    try:
        while not task.done():
            if cancelled():
                raise RoutingError('cancelled')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            await asyncio.wait({task}, timeout=min(0.1, remaining))
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


def execute_routed(messages, policy, decision, *, model_factory, evidence_ids, cancelled, trace, allow_upgrade=True, owned_models=()):
    trace.update(task_id=trace.get('task_id') or str(uuid4()), rule_id=decision.rule_id,
                 rule_version=decision.rule_version, reason=decision.reason, selected_role=decision.role,
                 status='running', attempts=[])
    frozen = copy.deepcopy(messages)
    loop = asyncio.new_event_loop()
    used_models = []
    try:
        for role in ([decision.role, 'high'] if decision.role == 'low' and allow_upgrade else [decision.role]):
            if cancelled():
                raise RoutingError('cancelled')
            model = model_factory(role)
            used_models.append(model)
            attempt = {'attempt_id': str(uuid4()), 'role': role, 'model_id': getattr(policy, role)['model_id'],
                       'model_name': getattr(model, 'model_name', None),
                       'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'running',
                       'usage': {}, 'usage_source': 'unknown', 'error': None}
            trace['attempts'].append(attempt)
            started = time.monotonic()
            iterator = model.astream(copy.deepcopy(frozen), config={
                'run_id': attempt['attempt_id'], 'metadata': {'routing_task_id': trace['task_id'],
                'routing_model_id': attempt['model_id'], 'routing_role': role}}).__aiter__()
            chunks, size, text, emitted = [], 0, '', False
            try:
                while True:
                    try:
                        chunk = loop.run_until_complete(next_chunk(iterator, started + policy.timeout, cancelled))
                    except StopAsyncIteration:
                        break
                    if not isinstance(chunk.content, str):
                        raise RoutingError('non_text_response')
                    reasoning = chunk.additional_kwargs.get('reasoning_content', '') or ''
                    if not isinstance(reasoning, str):
                        raise RoutingError('non_text_response')
                    size += len(chunk.content.encode('utf-8')) + len(reasoning.encode('utf-8'))
                    if size > policy.buffer_bytes:
                        raise RoutingError('buffer_limit')
                    response_model = (getattr(chunk, 'response_metadata', None) or {}).get('model_name')
                    if response_model:
                        attempt['response_model'] = response_model
                    usage = getattr(chunk, 'usage_metadata', None)
                    if usage:
                        for key in ('input_tokens', 'output_tokens'):
                            value = usage.get(key)
                            previous = attempt['usage'].get(key, 0)
                            attempt['usage'][key] = (previous + value if type(previous) is int
                                                    and type(value) is int and value >= 0 else None)
                        attempt['usage_source'] = 'provider'
                        # Cache detail remains a separate nullable measurement, never guessed from totals.
                        cache = (usage.get('input_token_details') or {}).get('cache_read')
                        if cache is not None:
                            attempt['usage']['cache_read_tokens'] = cache
                    if policy.contract.enabled:
                        text += chunk.content
                        chunks.append(chunk)
                    else:
                        emitted = True
                        yield chunk
                errors = validate_output(text, policy.contract, evidence_ids)
                if errors:
                    raise RoutingError(errors[0])
                if cancelled():
                    raise RoutingError('cancelled')
                attempt['status'] = 'succeeded'
                trace['status'] = 'succeeded'
                yield from chunks
                return
            except Exception as exc:
                code = error_code(exc)
                attempt.update(status='failed', error=code)
                if (role != 'low' or not allow_upgrade or emitted or code not in {'invalid_json', 'json_object_required', 'missing_fields',
                                                           'invalid_citations', 'unknown_citation', 'timeout',
                                                           'transport_error'}):
                    raise RoutingError(code) from None
                trace['upgrade_reason'] = code
            finally:
                attempt.update(ended_at=datetime.now(timezone.utc).isoformat(),
                               elapsed_seconds=time.monotonic() - started)
                trace['usage'] = summarize_attempts(trace['attempts'])
                close = getattr(iterator, 'aclose', None)
                if close:
                    loop.run_until_complete(close())
    except Exception as exc:
        code = error_code(exc)
        trace.update(status='cancelled' if code == 'cancelled' else 'failed', error=code)
        raise RoutingError(code) from None
    finally:
        trace['usage'] = summarize_attempts(trace['attempts'])
        for model in {id(m): m for m in [*used_models, *owned_models]}.values():
            async_client = getattr(model, 'root_async_client', None)
            if async_client is not None:
                loop.run_until_complete(async_client.close())
            client = getattr(model, 'root_client', None)
            if client is not None:
                client.close()
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
