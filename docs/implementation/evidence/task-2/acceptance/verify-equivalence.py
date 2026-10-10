"""Offline proof of context off/on equivalence; does not fabricate a second model run."""
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def main():
    dataset = json.loads((ROOT / 'frozen-v1.json').read_text())
    corpus = json.loads((ROOT / 'corpus.json').read_text())
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    assert digest(dataset) == manifest['datasets']['frozen-v1']
    assert digest(corpus) == manifest['corpus_hash']
    snapshot = json.loads((ROOT / 'frozen-retrieval/snapshot.json').read_text())
    previous = json.loads((ROOT / 'reused-snapshot.json').read_text())
    for field in ('model_id', 'model_revision', 'model_params', 'prompt', 'system',
                  'dialogue_number', 'knowledge_hash', 'dataset_hash'):
        assert snapshot[field] == previous[field], field
    assert json.loads((ROOT / 'frozen-retrieval/completion.json').read_text())['knowledge_unchanged']
    with gzip.open(ROOT / 'reused-answers.jsonl.gz', 'rt') as stream:
        reused = {r['case_id']: r for r in map(json.loads, stream)}
    rows = [json.loads(p.read_text()) for p in (ROOT / 'frozen-retrieval').glob('frozen-*.json')]
    by = {(r['case_id'], r['enabled']): r for r in rows}
    assert len(rows) == len(by) == 160
    checked_turns = removed = judge_calls = 0
    failures = []
    for case in dataset['cases']:
        cid = case['case_id']
        off, on, old = by[cid, False], by[cid, True], reused[cid]
        if case['scenario'].startswith('tool_'):
            assert off['status'] == on['status'] == old['status'] == 'not_applicable'
            continue
        assert off['status'] == on['status'] == 'retrieval_only'
        assert old['status'] == 'success'
        assert len(off['turns']) == len(on['turns']) == len(old['turns']) == len(case['turns'])
        history = []
        for a, b, original in zip(off['turns'], on['turns'], old['turns']):
            assert a['trace']['data'] == b['trace']['data'] == original['trace']['data']
            assert a['model_input'] == b['model_input']
            human = a['model_input'][-1]
            messages = ([snapshot['system']] if snapshot['system'] else [])
            if snapshot['dialogue_number']:
                messages += history[-2 * snapshot['dialogue_number']:]
            messages.append(human)
            assert messages == original['model_input'], cid
            history += [human, original['answer']]
            audit = b['trace']['context_processing']
            assert audit['semantic']['status'] == 'no_approved_match'
            removed += audit['original_count'] - audit['retained_count']
            judge_calls += audit['semantic']['judge_calls']
            checked_turns += 1
        if old['score']['evidence_recall'] is not None and old['score']['evidence_recall'] < 1:
            failures.append(cid)
    assert checked_turns == 211 and removed == judge_calls == 0
    report = {'dataset_cases': 80, 'applicable_cases': 68, 'tool_cases_not_applicable': 12,
              'paired_retrieval_records': 136, 'paired_turns': checked_turns,
              'context_off_on_equal': True, 'reconstructed_full_prompts_equal_to_reused_run': True,
              'knowledge_unchanged': True, 'removed_paragraphs': removed, 'online_semantic_judge_calls': judge_calls,
              'missing_required_evidence_cases': failures,
              'causal_input_reduction_tokens': 0,
              'reused_run_only': {field: sum(r[field] for r in reused.values() if r['status'] == 'success')
                                  for field in ('input_tokens', 'output_tokens')},
              'independent_new_off_on_model_runs': False,
              'human_review': 'pending', 'actual_bill': None}
    recalls = [r['score']['evidence_recall'] for r in reused.values()
               if r['status'] == 'success' and r['score']['evidence_recall'] is not None]
    report['required_evidence_recall'] = {'scored_cases': len(recalls),
                                          'macro_mean': sum(recalls) / len(recalls)}
    elapsed = sorted(r['elapsed_ms'] for r in reused.values() if r['status'] == 'success')
    report['reused_run_only']['p95_case_elapsed_ms'] = elapsed[math.ceil(.95 * len(elapsed)) - 1]
    report['fresh_retrieval_only'] = {}
    for enabled, label in ((False, 'off'), (True, 'on')):
        times = sorted(sum(t['retrieval_ms'] for t in r['turns']) for r in rows
                       if r['enabled'] == enabled and r['status'] == 'retrieval_only')
        report['fresh_retrieval_only'][label] = {'mean_case_ms': sum(times) / len(times),
                                               'p95_case_ms': times[math.ceil(.95 * len(times)) - 1]}
    (ROOT / 'equivalence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
