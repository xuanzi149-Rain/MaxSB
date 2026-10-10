"""Rebuild AI review summaries and conditional token amortization; no model calls."""
import json
import math
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text())


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


cases = {c['case_id']: c for c in read('frozen-v1.json')['cases']}
packets = sum((read(f'review/packet-{s}.json') for s in 'abc'), [])
reviews = sum((read(f'review/ai-review-{s}.json') for s in 'abc'), [])
assert len(reviews) == 68
assert len({r['case_id'] for r in reviews}) == 68
assert {r['case_id'] for r in reviews} == {r['case']['case_id'] for r in packets}
for r in reviews:
    assert r['human_correct'] is None and r['human_citation_accuracy'] is None
    assert isinstance(r['correct'], bool)
    assert len({c['id'] for c in r['citations']}) == len(r['citations'])


def metrics(rows):
    citations = [c for r in rows for c in r['citations']]
    return {
        'cases': len(rows), 'correct': sum(r['correct'] for r in rows),
        'accuracy': sum(r['correct'] for r in rows) / len(rows),
        'unique_citations_per_answer': len(citations),
        'supported_citations': sum(c['supported'] is True for c in citations),
        'uncertain_citations': sum(c['supported'] is None for c in citations),
        'failed_case_ids': [r['case_id'] for r in rows if not r['correct']],
    }


groups = defaultdict(list)
for row in reviews:
    groups[cases[row['case_id']]['scenario']].append(row)
semantic_reviews = read('review/ai-review-semantic.json')
assert len(semantic_reviews) == 24
assert len({(r['case_id'], r['repeat'], r['policy']) for r in semantic_reviews}) == 24
assert all(r['human_correct'] is None and r['human_citation_accuracy'] is None for r in semantic_reviews)
save('review-summary.json', {
    'reviewer_type': 'AI, not human signoff', 'frozen': metrics(reviews),
    'by_scenario': {k: metrics(v) for k, v in groups.items()},
    'historical_semantic': metrics(semantic_reviews), 'human_review': 'pending',
    'applicable_review_coverage': '68/68', 'overall_review_coverage': '68/80; 12 tool cases not applicable',
})
records = read('historical/reviewed/records.json')
initial = read('historical/judge-calls.json')
replay = read('historical/replay-judge-calls.json')
auditable = read('historical/auditable-judge-calls.json')
assert len(initial) == 36 and len(replay) == 6 and not auditable
cost = lambda rows: sum(r['input_tokens'] + r['output_tokens'] for r in rows)
by_case = []
for case_id in sorted({r['case_id'] for r in records}):
    rows = [r for r in records if r['case_id'] == case_id]
    assert {(r['repeat'], r['policy']) for r in rows} == {(i, p) for i in (1, 2) for p in ('on', 'off')}
    delta = {field: sum((1 if r['policy'] == 'off' else -1) * r[field] for r in rows) / 2
             for field in ('input_tokens', 'output_tokens')}
    judge = [r for r in initial if r['a_id'].rsplit('-', 1)[0] == case_id]
    assert len(judge) == 2
    saving = sum(delta.values())
    by_case.append({'case_id': case_id, 'mean_saved_per_hit': delta, 'total_saved_per_hit': saving,
                    'cold_judge_tokens': cost(judge), 'strict_positive_hits': math.floor(cost(judge) / saving) + 1})
target_cost = sum(r['cold_judge_tokens'] for r in by_case)
all_cost = cost(initial + replay + auditable)
mean_saving = sum(r['total_saved_per_hit'] for r in by_case) / len(by_case)
observed_saving = sum(r['total_saved_per_hit'] * 2 for r in by_case)
before, after = read('budget-before.json'), read('budget-after.json')
save('amortization.json', {
    'unit': 'provider input + output token count; NOT currency or invoice',
    'per_case': by_case, 'target_six_judge_tokens': target_cost,
    'all_known_judge_calls': len(initial + replay), 'all_known_judge_tokens': all_cost,
    'observed_paired_benchmark_saved_tokens': observed_saving,
    'net_vs_target_setup_tokens': observed_saving - target_cost,
    'net_vs_all_exploration_tokens': observed_saving - all_cost,
    'balanced_mean_saved_tokens_per_effective_hit': mean_saving,
    'conditional_target_strict_positive_hits_per_24h': math.floor(target_cost / mean_saving) + 1,
    'conditional_all_exploration_strict_positive_hits': math.floor(all_cost / mean_saving) + 1,
    'conditional_scenarios': [{'effective_hits_per_24h': n, 'net_tokens': n * mean_saving - target_cost}
                              for n in (6, 30, 180, 600)],
    'assumptions': ['same six-case balanced mix and observed mean savings',
                    'same setup cost each 24-hour approval TTL; actual future costs may differ',
                    'effective hits only; frozen corpus had zero matches',
                    'output savings are observed stochastic results, not guaranteed causal savings'],
    'real_long_term_traffic_observed': False, 'actual_bill': None,
    'this_turn_new_model_requests': after['requests'] - before['requests'],
    'this_turn_reservation_delta_cny': str(Decimal(after['reserved_cny']) - Decimal(before['reserved_cny'])),
})
lines = ['# 任务 2 人工复核待签收表', '',
         '以下为 AI 候选判断，尚未人工签收。请逐项核对问题、完整上下文与答案后填写人工结论；不要批量视为已通过。',
         '完整模型输入见对应 packet JSON；引用判断见 ai-review JSON。12 道工具题不适用。', '']
lookup = {r['case_id']: r for r in reviews}
for packet in packets:
    c = packet['case']
    r = lookup[c['case_id']]
    lines += [f"## {c['case_id']} · {c['scenario']}", '',
              '问题序列：' + ' → '.join(c['turns']), '',
              '关键事实：' + '；'.join(c['expected_facts']), '',
              '实际回答：', '', packet['answer'], '',
              'AI 判断：' + ('通过' if r['correct'] else '不通过') + '。' + r['reasoning'], '',
              '人工结论：待填写；复核人：待填写；时间：待填写；依据及修订记录：待填写。', '']
(ROOT / 'review/human-signoff.md').write_text('\n'.join(lines))
print(json.dumps({'review': metrics(reviews), 'judge_cost': all_cost, 'saved': observed_saving}, ensure_ascii=False))
