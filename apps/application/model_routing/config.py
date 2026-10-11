# coding=utf-8
"""Strict opt-in configuration; provider credentials are never node parameters."""
import math
from uuid import UUID
from .types import OutputContract, RoutingPolicy

PARAMETERS = {'temperature', 'top_p', 'max_tokens', 'max_completion_tokens', 'presence_penalty',
              'frequency_penalty', 'seed', 'enable_thinking'}


def parse_policy(value: dict) -> RoutingPolicy:
    if not isinstance(value, dict) or type(value.get('enabled', False)) is not bool:
        raise ValueError('routing_invalid_config')
    if not value.get('enabled', False):
        return RoutingPolicy()
    if set(value) - {'enabled', 'low', 'high', 'contract', 'timeout'}:
        raise ValueError('routing_unknown_field')
    models = []
    for role in ('low', 'high'):
        model = value.get(role)
        if not isinstance(model, dict) or set(model) - {'model_id', 'params'}:
            raise ValueError('routing_invalid_model')
        try:
            identity = str(UUID(model['model_id']))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError('routing_invalid_model') from exc
        params = model.get('params', {})
        if not isinstance(params, dict) or set(params) - PARAMETERS:
            raise ValueError('routing_invalid_params')
        for key, item in params.items():
            if key == 'enable_thinking':
                valid = type(item) is bool
            else:
                valid = type(item) in (int, float) and math.isfinite(item)
            if valid and key in ('max_tokens', 'max_completion_tokens'):
                valid = type(item) is int and 1 <= item <= 131072
            elif valid and key == 'seed':
                valid = type(item) is int and -(2 ** 31) <= item < 2 ** 31
            elif valid and key in ('temperature', 'top_p', 'presence_penalty', 'frequency_penalty'):
                lower, upper = {'temperature': (0, 2), 'top_p': (0, 1),
                                'presence_penalty': (-2, 2), 'frequency_penalty': (-2, 2)}[key]
                valid = lower <= item <= upper
            if not valid:
                raise ValueError('routing_invalid_params')
        models.append({'model_id': identity, 'params': dict(params)})
    if models[0]['model_id'] == models[1]['model_id']:
        raise ValueError('routing_models_must_differ')
    timeout = value.get('timeout', 60)
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError('routing_invalid_timeout')
    contract = value.get('contract', {})
    if not isinstance(contract, dict) or set(contract) - {'required_fields', 'citation_field', 'evidence_reference'}:
        raise ValueError('routing_invalid_contract')
    fields = contract.get('required_fields', [])
    if (not isinstance(fields, list) or len(fields) > 64
            or any(not isinstance(k, str) or not 1 <= len(k) <= 128 for k in fields)
            or len(set(fields)) != len(fields)):
        raise ValueError('routing_invalid_fields')
    citation = contract.get('citation_field', '')
    reference = contract.get('evidence_reference', [])
    if (not isinstance(citation, str) or len(citation) > 128 or not isinstance(reference, list)
            or (citation and (len(reference) != 2 or not all(isinstance(k, str) and k for k in reference)))
            or (reference and not citation)):
        raise ValueError('routing_invalid_evidence_reference')
    return RoutingPolicy(True, *models, OutputContract(tuple(fields), citation, tuple(reference)), timeout)
