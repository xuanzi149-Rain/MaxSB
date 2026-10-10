# coding=utf-8
from application.evaluation.metrics import summarize


def compare_runs(left: dict, right: dict) -> dict:
    reasons = [key for key in ('dataset_hash', 'config_hash') if left.get(key) != right.get(key)]
    for key in ('image_id',):
        if left.get('snapshot', {}).get(key) != right.get('snapshot', {}).get(key):
            reasons.append(key)
    if left.get('status') != 'completed' or right.get('status') != 'completed':
        reasons.append('incomplete_run')
    left_cases = {r['case_id']: r for r in left['cases']}
    right_cases = {r['case_id']: r for r in right['cases']}
    return {'comparable': not reasons, 'reasons': reasons,
            'left_summary': summarize(left['cases'], total_cases=left.get('total')), 'right_summary': summarize(right['cases'], total_cases=right.get('total')),
            'cases': [{'case_id': key, 'left': left_cases.get(key), 'right': right_cases.get(key),
                       'unmatched': key not in left_cases or key not in right_cases}
                      for key in sorted(left_cases.keys() | right_cases.keys())]}
