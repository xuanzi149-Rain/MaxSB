import json
import gzip
import hashlib
import math
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parent
run = root / 'frozen-real'
with tarfile.open(root / 'sealed-inputs.tar.gz') as archive:
    dataset = json.load(archive.extractfile('frozen-v1.json'))
    manifest = json.load(archive.extractfile('manifest.json'))
    corpus = json.load(archive.extractfile('corpus.json'))
for value, sha in [(dataset, manifest['datasets']['frozen-v1']), (corpus, manifest['corpus_hash'])]:
    assert hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest() == sha
expected = {c['case_id']: c for c in dataset['cases']}
rows = [json.loads(p.read_text()) for p in sorted(run.glob('frozen-*.json'))]
if len(rows) != 160:
    with gzip.open(run / 'cases.jsonl.gz', 'rt', encoding='utf-8') as stream:
        rows = [json.loads(line) for line in stream]
assert len(rows) == 160
assert {(r['case_id'], r['enabled']) for r in rows} == {(c, b) for c in expected for b in (False, True)}
completion = json.loads((run / 'completion.json').read_text())
snapshot = json.loads((run / 'snapshot.json').read_text())
assert completion['knowledge_unchanged'] is True
assert snapshot['dataset_hash'] == manifest['datasets']['frozen-v1']
assert snapshot['retrieval_only'] is False
checks = {'records': len(rows), 'knowledge_unchanged': True, 'scope': snapshot['scope'], 'strategies': {}}
for enabled, label in ((False, 'fixed'), (True, 'dynamic')):
    group = [r for r in rows if r['enabled'] == enabled and r['status'] != 'not_applicable']
    assert len(group) == 68
    success = [r for r in group if r['status'] == 'success']
    for row in success:
        assert len(row['turns']) == len(expected[row['case_id']]['turns'])
        for field in ('input_tokens', 'output_tokens'):
            values = [t[field] for t in row['turns']]
            assert row[field] == (sum(values) if all(v is not None for v in values) else None)
    usage = {}
    for field in ('input_tokens', 'output_tokens'):
        values = [r[field] for r in group]
        usage[field + '_coverage'] = sum(v is not None for v in values)
        usage[field + '_total'] = sum(values) if all(v is not None for v in values) else None
        usage[field + '_mean_per_case'] = usage[field + '_total'] / len(group) if usage[field + '_total'] is not None else None
    elapsed = sorted(r['elapsed_ms'] for r in group)
    checks['strategies'][label] = {'cases': len(group), 'success': len(success),
        'failed_case_ids': [r['case_id'] for r in group if r['status'] != 'success'],
        'model_calls_recorded': sum(len(r['turns']) for r in group), **usage,
        'p95_case_elapsed_ms': elapsed[math.ceil(.95 * len(elapsed)) - 1], 'actual_cost': None}
by_id = {(r['case_id'], r['enabled']): r for r in rows}
checks['evidence_recall_regressions'] = [cid for cid in expected
    if by_id[cid, True]['score']['evidence_recall'] is not None
    and by_id[cid, True]['score']['evidence_recall'] < by_id[cid, False]['score']['evidence_recall']]
for field in ('input_tokens', 'output_tokens'):
    a = checks['strategies']['fixed'][field + '_total']
    b = checks['strategies']['dynamic'][field + '_total']
    checks[field + '_relative_change'] = (b-a)/a if a else None
before = json.loads((root / 'budget-before-real.json').read_text())
after = json.loads((root / 'budget-after-real.json').read_text())
from decimal import Decimal
checks['budget'] = {'request_delta': after['requests']-before['requests'],
    'reservation_delta_cny': str(Decimal(after['reserved_cny'])-Decimal(before['reserved_cny'])),
    'reserved_after_cny': after['reserved_cny'], 'limit_cny': after['limit_cny'], 'actual_bill': None}
checks['successful_calls_plus_smoke'] = sum(v['model_calls_recorded'] for v in checks['strategies'].values()) + 2
checks['ledger_request_count_matches'] = checks['budget']['request_delta'] == checks['successful_calls_plus_smoke']
checks['turns_at_output_limit'] = [
    {'case_id': r['case_id'], 'enabled': r['enabled'], 'turn': index + 1}
    for r in rows for index, turn in enumerate(r['turns'])
    if turn.get('output_tokens') is not None and turn['output_tokens'] >= 2048]
checks['human_correctness_and_citation_review'] = 'pending'
with tarfile.open(root / 'real-runtime-source.tar.gz') as archive:
    for name, expected_sha in snapshot['source_files'].items():
        assert hashlib.sha256(archive.extractfile(name).read()).hexdigest() == expected_sha
checks['runtime_source_archive_matches_snapshot'] = True
assert checks['ledger_request_count_matches']
(root / 'real-verification.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2))
print(json.dumps(checks, ensure_ascii=False, indent=2))
