# coding=utf-8
"""Rules provide diagnostics, not a substitute for human semantic review."""


def score_case(case: dict, result: dict) -> dict:
    required = set(case.get('required_evidence_ids', []))
    retrieved = set(result.get('retrieved_evidence_ids', []))
    groups = case.get('required_evidence_groups') or [[item] for item in sorted(required)]
    matched = sum(bool(set(group) & retrieved) for group in groups)
    expectation = case.get('tool_expectation')
    tool_complete = None
    if expectation:
        events = result.get('tool_events', [])
        tool_complete = result.get('status') == 'success' and expectation.get('outcome') == 'success' and any(all(event.get(key) == value for key, value in expectation.items()) for event in events)
    return {'correct': None, 'citation_accuracy': None,
            'evidence_recall': matched / len(groups) if groups and 'retrieved_evidence_ids' in result else None,
            'missing_evidence_ids': sorted(required - retrieved), 'tool_complete': tool_complete,
            'fact_mentions': [fact in result.get('answer', '') for fact in case.get('expected_facts', [])],
            'review_status': 'pending'}
