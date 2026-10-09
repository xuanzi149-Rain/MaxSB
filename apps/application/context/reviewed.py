# coding=utf-8
"""Explicitly reviewed, cache-only semantic selection for authorized evidence.

Approvals are trusted operator artifacts, never model output or request-provided
configuration. Bind each approval to the exact pair key AND cached judgements.
This adapter does not perform model calls, embedding, or cache renewal.
"""
from application.context.processor import process_context, validate_config
from application.context.semantic import (
    JUDGE_PROMPT, RULE_VERSION, decision, digest, evidence, guard, signature, validate_judgement,
)


def pair_key(a, b, namespace, versions):
    a, b = sorted([evidence(a), evidence(b)], key=digest)
    return digest({'namespace': namespace, 'versions': versions, 'rule': RULE_VERSION,
                   'prompt': JUDGE_PROMPT, 'a': a, 'b': b})


def apply_reviewed_context(items, config=None, *, cache, approvals, namespace, versions,
                           render=None, max_chars=100000, separator='\n'):
    """Only exact approved, unexpired, bidirectionally equivalent pairs may merge.

    Caller provides the current workspace/access namespace and current model
    versions. Inputs must already be authorized. Failure retains evidence under
    the existing deterministic/budget policy; it never invokes a fallback model.
    """
    enabled, _, _ = validate_config(config)
    relations, checks = set(), []
    valid_scope = (bool(namespace) and isinstance(versions, dict)
                   and all(versions.get(k) for k in ('judge', 'embedding')))
    if enabled and valid_scope and isinstance(approvals, dict) and len(items) <= 50 and len(approvals) <= 100:
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                try:
                    a, b = sorted([evidence(items[i]), evidence(items[j])], key=digest)
                    if guard(a, b):
                        continue
                    key = pair_key(a, b, namespace, versions)
                    if key not in approvals:
                        continue
                    row = {'pair_key': key, 'a_id': a['id'], 'b_id': b['id'], 'status': 'keep_unavailable'}
                    checks.append(row)
                    cached = cache.get(key)
                    if cached is None or digest(cached) != approvals[key]:
                        continue
                    forward = validate_judgement(cached['forward'], a, b)
                    backward = validate_judgement(cached['backward'], b, a)
                    if (decision(forward) != 'review_equivalent'
                            or signature(forward) != signature(backward, reverse=True)):
                        row['status'] = 'keep_not_equivalent'
                        continue
                    relations.add((i, j))
                    row['status'] = 'approved_equivalent'
                except Exception:
                    # Malformed or unavailable cache cannot remove evidence.
                    continue
    result = process_context(items, config, render=render, max_chars=max_chars, separator=separator,
                             _reviewed_pairs=relations)
    mapping = (result['audit'] or {}).get('mapping', [])
    result['semantic_application'] = {
        'mode': 'reviewed_cache_only' if enabled else 'disabled', 'judge_calls': 0,
        'approved_pair_count': len(relations), 'checks': checks,
        'actual_removed_count': sum(m['reason'] == 'semantic_duplicate' for m in mapping),
    }
    return result
