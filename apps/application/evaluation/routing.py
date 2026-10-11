# coding=utf-8
"""Price-derived costs never replace actual bills; strict matched three-arm comparison."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from .metrics import summarize


def price_attempt(attempt, price):
    result = {'priced_cost': None, 'actual_cost': attempt.get('actual_cost'),
              'currency': price.get('currency'), 'price_version': price.get('version'),
              'price_source': price.get('source'), 'price_basis': price.get('basis', 'reference_price')}
    try:
        at = datetime.fromisoformat(attempt['started_at'])
        if not (price.get('version') and price.get('source') and price.get('currency')
                and datetime.fromisoformat(price['valid_from']) <= at < datetime.fromisoformat(price['valid_until'])):
            return result
        usage = attempt['usage']
        inputs, outputs = usage['input_tokens'], usage['output_tokens']
        if inputs is None or inputs > price.get('max_input_tokens', 10 ** 9):
            return result
        cache = usage.get('cache_read_tokens', 0) if 'cache_per_million' not in price else usage['cache_read_tokens']
        if any(type(v) is not int or v < 0 for v in (inputs, outputs, cache)) or cache > inputs:
            return result
        rates = [Decimal(str(price[k])) for k in ('input_per_million', 'output_per_million')]
        cached = Decimal(str(price.get('cache_per_million', price['input_per_million'])))
        if any(not v.is_finite() or v < 0 for v in [*rates, cached]):
            return result
        result['priced_cost'] = str(((inputs - cache) * rates[0] + outputs * rates[1] + cache * cached)
                                    / Decimal(1000000))
    except (KeyError, ValueError, TypeError, InvalidOperation):
        pass
    return result


def compare_routing(groups, protocol):
    roles = ('low', 'high', 'routing')
    reasons = []
    if set(groups) != set(roles):
        return {'comparable': False, 'reasons': ['missing_groups'], 'quality_passed': False, 'cost_optimized': False}
    for key in ('dataset_hash', 'contract_hash'):
        values = [groups[k].get(key) for k in roles]
        if not values[0] or len(set(values)) != 1:
            reasons.append(key)
    for key in ('image_id', 'code_sha', 'local_diff_hash', 'evaluation_source_hash', 'routing_protocol_hash'):
        values = [groups[k].get('snapshot', {}).get(key) for k in roles]
        if values[0] in (None, '', 'unknown') or len(set(values)) != 1:
            reasons.append(key)
    by_role = {role: {r['case_id']: r for r in groups[role]['cases']} for role in roles}
    if (not by_role['high'] or any(set(by_role[r]) != set(by_role['high'])
            or len(by_role[r]) != len(groups[r]['cases']) for r in roles)):
        reasons.append('case_mismatch')
    scenarios = sorted({r.get('scenario', 'unknown') for rows in by_role.values() for r in rows.values()})
    summaries = {role: summarize(groups[role]['cases']) for role in roles}
    per_scenario = {scenario: {role: summarize([r for r in groups[role]['cases']
                    if r.get('scenario', 'unknown') == scenario]) for role in roles} for scenario in scenarios}
    quality = not reasons
    for summary in [summaries, *per_scenario.values()]:
        high, routed = summary['high']['accuracy'], summary['routing']['accuracy']
        quality = quality and high is not None and routed is not None and routed >= high
    for key, high in by_role['high'].items():
        routed = by_role['routing'].get(key, {})
        h_evidence, r_evidence = high.get('score', {}).get('evidence_recall'), routed.get('score', {}).get('evidence_recall')
        if h_evidence is not None and (r_evidence is None or r_evidence < h_evidence):
            quality = False
        for row in (high, routed):
            review = row.get('review', {})
            if review.get('citation_total') is None or review.get('citation_supported') is None:
                quality = False
        h_review, r_review = high.get('review', {}), routed.get('review', {})
        if ((r_review.get('citation_total') or 0) - (r_review.get('citation_supported') or 0)
                > (h_review.get('citation_total') or 0) - (h_review.get('citation_supported') or 0)):
            quality = False
    high, routed = summaries['high'], summaries['routing']
    cheaper = (high['currency'] == routed['currency'] and high['cost_per_success'] is not None
               and routed['cost_per_success'] is not None and routed['cost_per_success'] < high['cost_per_success'])
    upgrade_count = sum(bool(r.get('model_routing', {}).get('upgrade_reason')) or
                        any((n.get('model_routing') or {}).get('upgrade_reason') for n in r.get('trace', []))
                        for r in groups['routing']['cases'])
    return {'comparable': not reasons, 'reasons': reasons, 'quality_passed': bool(quality),
            'cost_optimized': bool(quality and cheaper), 'summaries': summaries, 'by_scenario': per_scenario,
            'upgrade_rate': upgrade_count / len(by_role['routing']) if by_role['routing'] else None,
            'cost_basis': 'actual_bill', 'protocol': protocol}


def price_trace(trace, prices):
    """Attach immutable reference rates by configured model identity; never substitute a bill."""
    attempts = trace.get('attempts', [])
    for attempt in attempts:
        price = prices.get(attempt.get('model_id'), {})
        if price.get('model_name') != attempt.get('model_name'):
            price = {}
        attempt.update(price_attempt(attempt, price))
    values = [a.get('priced_cost') for a in attempts]
    currencies = {a.get('currency') for a in attempts}
    known = bool(attempts) and all(v is not None for v in values) and len(currencies) == 1 and None not in currencies
    trace['priced_cost'] = str(sum(Decimal(v) for v in values)) if known else None
    trace['currency'] = next(iter(currencies)) if known else None
    trace['actual_cost'] = None
    return trace
