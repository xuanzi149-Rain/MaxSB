# coding=utf-8
"""Deterministic whole-chunk selection; estimates are not provider token usage."""
import json
import math

from application.context.matching import clauses, comparison_text, contains, duplicate_kind, normalize


def estimate_tokens(text):
    # Language-independent heuristic; not a tokenizer or a guaranteed upper bound.
    return math.ceil(len(text.encode('utf-8')) / 3)


def validate_config(config):
    config = config or {}
    enabled = config.get('enabled', False)
    budget = config.get('token_budget', 2048)
    threshold = config.get('similarity_threshold', .95)
    if type(enabled) is not bool:
        raise ValueError('enabled must be boolean')
    if type(budget) is not int or not 1 <= budget <= 100000:
        raise ValueError('token_budget must be between 1 and 100000')
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not .8 <= threshold <= 1:
        raise ValueError('similarity_threshold must be between 0.8 and 1')
    return enabled, budget, threshold


def source(item):
    return {key: str(item[key]) if item.get(key) is not None else None
            for key in ('id', 'document_id', 'knowledge_id')}


def comparable_scores(items):
    for key in ('relevance_score', 'comprehensive_score', 'similarity'):
        values = [item.get(key) for item in items]
        if all(type(value) in (int, float) and math.isfinite(value) for value in values):
            return values
    return [None] * len(items)


def process_context(items, config=None, *, max_chars=100000, render=None, separator='\n', _reviewed_pairs=frozenset()):
    """Select original evidence objects, keeping output order and direct source mappings.

    Scoring chooses duplicate representatives and budget priority, never presentation
    order. Only a retained, fitting representative may cover another paragraph.
    """
    enabled, budget, threshold = validate_config(config)
    render = render or (lambda p: p.get('content') or '')
    rendered = [render(p) for p in items]
    original_text = separator.join(rendered)
    if not enabled:
        return {'retained': items, 'text': original_text, 'audit': None}
    texts = [comparison_text(p.get('content'), source_label=True) for p in items]
    scopes = [(comparison_text(p.get('title')), str(p.get('knowledge_id')),
               json.dumps(p.get('meta'), sort_keys=True, default=str)) for p in items]
    statements = [clauses(text) for text in texts]
    scores = comparable_scores(items)
    order = list(range(len(items)))
    if all(s is not None for s in scores):
        order.sort(key=lambda i: (-scores[i], -sum(v is not None for v in source(items[i]).values()), i))

    def relation(i, j):
        if scopes[i] != scopes[j]:
            return None
        duplicate = duplicate_kind(texts[i], texts[j], threshold)
        if duplicate:
            return duplicate
        if contains(statements[j], statements[i]):
            return 'contained'
        if tuple(sorted((i, j))) in _reviewed_pairs:
            return 'semantic_duplicate'
        return None

    selected, represented = [], {}
    for i in order:
        if not normalize(items[i].get('content')):
            continue
        representative = next((j for j in selected if relation(i, j)), None)
        if representative is not None:
            represented[representative].append(i)
            continue
        # A longer original can replace already selected clauses only if the full
        # replacement fits. Otherwise the shorter original remains available.
        replaced = [j for j in selected if relation(j, i) == 'contained'
                    and all(relation(k, i) for k in represented[j])]
        candidate_ids = sorted([j for j in selected if j not in replaced] + [i])
        candidate = separator.join(rendered[j] for j in candidate_ids)
        if len(candidate) <= max_chars and estimate_tokens(candidate) <= budget:
            selected = candidate_ids
            represented[i] = [i]
            for j in replaced:
                represented[i].extend(represented.pop(j))

    mapping = []
    for i, item in enumerate(items):
        origin = source(item)
        entry = {'original_index': i, 'original_id': origin['id'],
                 'document_id': origin['document_id'], 'knowledge_id': origin['knowledge_id'],
                 'retained_index': None, 'retained_id': None,
                 'reason': 'budget' if normalize(item.get('content')) else 'empty'}
        if i in selected:
            entry.update(reason='retained', retained_index=i, retained_id=origin['id'])
        elif normalize(item.get('content')):
            for j in selected:
                reason = relation(i, j)
                if reason:
                    entry.update(reason=reason, retained_index=j, retained_id=source(items[j])['id'])
                    break
        mapping.append(entry)
    text = separator.join(rendered[i] for i in selected)
    before, after = estimate_tokens(original_text), estimate_tokens(text)
    return {'retained': [items[i] for i in selected], 'text': text,
            'audit': {'enabled': True, 'original_count': len(items), 'retained_count': len(selected),
                      'estimated_original_tokens': before, 'estimated_retained_tokens': after,
                      'estimated_saved_tokens': before - after, 'token_estimator': 'utf8_bytes_div_3_v1',
                      'token_budget': budget, 'max_chars': max_chars, 'similarity_threshold': threshold,
                      'mapping': mapping}}
