# coding=utf-8
"""Auditable metrics. Unknown is never coerced to zero."""
import math
from decimal import Decimal


def summarize(results: list[dict], total_cases=None) -> dict:
    count = len(results) if total_cases is None else total_cases
    reviewed = [r for r in results if type(r.get('review', {}).get('correct')) is bool
                and r['review'].get('reviewer')]
    correct = sum(r['review']['correct'] and r.get('status') == 'success' for r in reviewed)
    summary = {'count': count, 'review_coverage': len(reviewed) / count if count else 0,
               'accuracy': correct / count if count and len(reviewed) == count else None,
               'confirmed_correct_fraction': correct / count if count else None,
               'successful_execution_count': sum(r.get('status') == 'success' for r in results),
               'cost_per_success': None, 'actual_cost': None, 'currency': None}
    for field in ('input_tokens', 'output_tokens'):
        values = [r[field] for r in results if r.get(field) is not None]
        summary['average_' + field] = sum(values) / len(values) if values else None
        summary[field.replace('_tokens', '_token_coverage')] = len(values) / count if count else 0
    times = sorted(r['elapsed_seconds'] for r in results if r.get('elapsed_seconds') is not None)
    summary['p95_seconds'] = times[math.ceil(.95 * len(times)) - 1] if times else None
    summary['latency_sample_count'] = len(times)
    for field in ('evidence_recall', 'tool_complete'):
        values = [r.get('score', {}).get(field) for r in results]
        values = [v for v in values if v is not None]
        summary[field] = sum(values) / len(values) if values else None
        summary[field + '_sample_count'] = len(values)
    citation_reviews = [r['review'] for r in reviewed if r['review'].get('citation_total') is not None]
    total = sum(r['citation_total'] for r in citation_reviews)
    summary['citation_accuracy'] = sum(r.get('citation_supported', 0) for r in citation_reviews) / total if total else None
    summary['citation_reviewed_count'] = total
    costs = [r.get('actual_cost') for r in results]
    currencies = {r.get('currency') for r in results}
    if count and len(results) == count and all(v is not None for v in costs) and len(currencies) == 1 and None not in currencies:
        cost = sum(Decimal(str(v)) for v in costs)
        summary.update(actual_cost=float(cost), currency=next(iter(currencies)))
        if correct and len(reviewed) == count:
            summary['cost_per_success'] = float(cost / correct)
    summary['cost_coverage'] = sum(v is not None for v in costs) / count if count else 0
    return summary
