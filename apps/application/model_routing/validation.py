# coding=utf-8
"""Machine validation only, never an assertion of factual correctness."""
import json
import math


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('nonfinite_number')


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite_number')
    return number


def validate_output(text, contract, evidence_ids):
    if not contract.enabled:
        return []
    try:
        parsed = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
    except (ValueError, TypeError, RecursionError):
        return ['invalid_json']
    if not isinstance(parsed, dict):
        return ['json_object_required']
    errors = ['missing_fields'] if any(k not in parsed for k in contract.required_fields) else []
    if contract.citation_field:
        citations = parsed.get(contract.citation_field)
        if not isinstance(citations, list) or any(not isinstance(k, str) for k in citations):
            errors.append('invalid_citations')
        elif any(k not in evidence_ids for k in citations):
            errors.append('unknown_citation')
    return errors
