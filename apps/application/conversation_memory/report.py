# coding=utf-8
"""Paired totals never count missing provider usage as zero."""


def summarize(rows):
    ids = sorted({r['case_id'] for r in rows})
    paired = [key for key in ids if {r['strategy'] for r in rows if r['case_id'] == key} == {'fixed', 'memory'}
              and not any(r.get('error') for r in rows if r['case_id'] == key)]
    result = {'paired_cases': paired, 'failed_cases': [key for key in ids if key not in paired],
              'human_correctness': None, 'human_review': 'pending'}
    for strategy in ('fixed', 'memory'):
        subset = [r for r in rows if r['strategy'] == strategy and r['case_id'] in paired]
        result[strategy] = {key: (sum(r['usage'][key] for r in subset)
                                 if subset and all(isinstance(r.get('usage', {}).get(key), int) for r in subset)
                                 else None) for key in ('input_tokens', 'output_tokens')}
        result[strategy]['cost'] = None
    return result
