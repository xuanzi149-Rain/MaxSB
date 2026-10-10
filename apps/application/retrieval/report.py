# coding=utf-8
"""Per-category paired reports; unknown billing and review values stay unknown."""


def mean_known(values):
    known = [value for value in values if value is not None]
    return sum(known) / len(known) if known else None


def summarize_pairs(rows, group_by='category'):
    if group_by not in ('category', 'scenario'):
        raise ValueError('Group by the policy category or the independently annotated dataset scenario')
    report = {}
    categories = ('none', 'simple', 'complex', 'unknown') if group_by == 'category' else sorted(
        {row['scenario'] for row in rows})
    for category in categories:
        report[category] = {}
        for label, enabled in (('fixed', False), ('dynamic', True)):
            group = [r for r in rows if r[group_by] == category and r['enabled'] == enabled
                     and r['status'] != 'not_applicable']
            summary = {'count': len(group), 'success_count': sum(r['status'] == 'success' for r in group),
                       'execution_failures': [r['case_id'] for r in group if r['status'] == 'failed'],
                       'quality_failures': [r['case_id'] for r in group
                                            if r['score'].get('correct') is False or
                                            (r['score'].get('evidence_recall') is not None
                                             and r['score']['evidence_recall'] < 1)],
                       'missing_evidence': {r['case_id']: r['score']['missing_evidence_ids'] for r in group
                                            if r['score'].get('missing_evidence_ids')}}
            for field in ('input_tokens', 'output_tokens', 'actual_cost'):
                summary[field] = mean_known([r.get(field) for r in group])
                summary[field + '_coverage'] = sum(r.get(field) is not None for r in group)
            for field, output in (('correct', 'correctness'), ('citation_accuracy', 'citation_accuracy'),
                                  ('evidence_recall', 'evidence_recall')):
                values = [r['score'].get(field) for r in group]
                summary[output] = mean_known(values)
                summary[output + '_coverage'] = sum(v is not None for v in values)
            summary['retrieval_ms'] = mean_known([
                sum(t['retrieval_ms'] for t in r['turns']) for r in group if r['turns']])
            report[category][label] = summary
    return report
