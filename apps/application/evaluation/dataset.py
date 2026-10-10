# coding=utf-8
"""Versioned evaluation datasets; no Django or model dependencies."""
import hashlib
import json

SCENARIOS = {'direct', 'multi_evidence', 'duplicate', 'no_evidence', 'conversation',
             'tool_success', 'tool_timeout', 'conflict', 'routing'}


def dataset_digest(dataset: dict) -> str:
    return hashlib.sha256(json.dumps(dataset, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def validate_dataset(dataset: dict, corpus: dict) -> None:
    if not dataset.get('version') or dataset.get('split') not in ('dev', 'frozen'):
        raise ValueError('Invalid dataset version or split')
    evidence = {doc['evidence_id'] for doc in corpus['documents']}
    if len(evidence) != len(corpus['documents']):
        raise ValueError('Duplicate evidence ID')
    cases = dataset.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('Empty dataset')
    seen = set()
    for case in cases:
        case_id = case.get('case_id')
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError('Missing or duplicate case ID')
        seen.add(case_id)
        if case.get('scenario') not in SCENARIOS:
            raise ValueError('Unknown scenario')
        for key in ('turns', 'expected_facts', 'acceptable_answers'):
            values = case.get(key)
            if not isinstance(values, list) or not values or not all(isinstance(v, str) and v.strip() for v in values):
                raise ValueError('Invalid ' + key)
        required = case.get('required_evidence_ids')
        if not isinstance(required, list) or not set(required).issubset(evidence):
            raise ValueError('Unknown evidence')
        groups = case.get('required_evidence_groups', [])
        if not isinstance(groups, list) or any(not isinstance(group, list) or not group
                                               or not set(group).issubset(evidence) for group in groups):
            raise ValueError('Invalid alternative evidence groups')
        if not isinstance(case.get('rubric'), dict) or not all(case['rubric'].get(k) for k in ('correct', 'failure')):
            raise ValueError('Missing rubric')
        if 'tool_expectation' not in case:
            raise ValueError('Missing tool expectation')
