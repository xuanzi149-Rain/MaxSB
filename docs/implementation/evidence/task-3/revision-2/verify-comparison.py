import json,hashlib,tarfile
from pathlib import Path
r=Path(__file__).resolve().parent
manifest=json.loads((r/'inputs/manifest.json').read_text())
for name in ['acceptance-v2','dev-v2','corpus']:
 value=json.loads((r/'inputs'/f'{name}.json').read_text())
 expected=manifest['corpus_hash'] if name=='corpus' else manifest['datasets'][name]
 assert hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()==expected
inputs=json.loads((r/'inputs/acceptance-v2.json').read_text())
cases={c['case_id']:c for c in inputs['cases']}
report={}
for name in ['shared','free-1','free-2']:
 folder=r/name
 assert (folder/'completion.json').exists(), name
 snapshot=json.loads((folder/'snapshot.json').read_text())
 assert snapshot['dataset_hash']==manifest['datasets']['acceptance-v2']
 archive_name='shared-runtime-source.tar.gz' if name=='shared' else 'free-runtime-source.tar.gz'
 with tarfile.open(r/archive_name) as archive:
  for path,expected_hash in snapshot['source_files'].items():
   assert hashlib.sha256(archive.extractfile(path).read()).hexdigest()==expected_hash,path
 rows=[json.loads(p.read_text()) for p in sorted(folder.glob('v2-*.json'))]
 assert len(rows)==26
 failed=[{'case_id':row['case_id'],'enabled':row['enabled'],'error':row.get('error')} for row in rows if row['status']!='success']
 assert json.loads((folder/'completion.json').read_text())['knowledge_unchanged']
 by={(row['case_id'],row['enabled']):row for row in rows}
 assert len(by)==26
 for cid,c in cases.items():
  for enabled in [False,True]:
   row=by[cid,enabled]
   if row['status']!='success':
    assert row['input_tokens'] is None and row['output_tokens'] is None
    continue
   assert len(row['turns'])==len(c['turns'])
   for field in ['input_tokens','output_tokens']:
    assert row[field]==sum(t[field] for t in row['turns'])
   if name=='shared':
    for x,y in zip(by[cid,False]['turns'],by[cid,True]['turns']):
     assert x['model_input'][:-1]==y['model_input'][:-1]
 excluded=sorted({x['case_id'] for x in failed})
 recorded_calls=sum(len(x['turns']) for x in rows)
 rows=[x for x in rows if x['case_id'] not in excluded]
 result={'cases':13,'paired_cases':len(rows)//2,'requests_recorded':recorded_calls,
         'failed_records':failed,'excluded_pairs':excluded,'knowledge_unchanged':True,'strategies':{}}
 for enabled,label in [(False,'fixed'),(True,'dynamic')]:
  group=[x for x in rows if x['enabled']==enabled]
  controls=[t for x in group for t,intent in zip(x['turns'],cases[x['case_id']]['expected_retrieval_intents']) if intent=='skip']
  result['strategies'][label]={f:sum(x[f] for x in group) for f in ['input_tokens','output_tokens']}
  result['strategies'][label].update(control_output_tokens=sum(t['output_tokens'] for t in controls),
   control_max_output_tokens=max(t['output_tokens'] for t in controls),
   removed_contexts=sum(t['dialogue_policy']['removed_contexts'] for x in group for t in x['turns']),
   removed_chars=sum(t['dialogue_policy']['removed_chars'] for x in group for t in x['turns']))
 result['relative_change']={field:(result['strategies']['dynamic'][field]/result['strategies']['fixed'][field]-1)
                            for field in ['input_tokens','output_tokens']}
 result['recall_regressions']=[cid for cid in cases if cid not in excluded and by[cid,False]['score']['evidence_recall'] is not None
      and by[cid,True]['score']['evidence_recall']<by[cid,False]['score']['evidence_recall']]
 result['incomplete_evidence']={label:[x['case_id'] for x in rows if x['enabled']==enabled
    and x['score']['evidence_recall'] is not None and x['score']['evidence_recall']<1]
    for enabled,label in [(False,'fixed'),(True,'dynamic')]}
 result['input_history_verified_identical']=name=='shared'
 result['output_limit_turns']=[x['case_id'] for x in rows if any(t['output_tokens']>=2048 for t in x['turns'])]
 report[name]=result
from decimal import Decimal
before=json.loads((r/'budget-before.json').read_text())
after=json.loads((r/'budget-after.json').read_text())
recorded=0
failed=0
for directory,prefix in [('dev-real','dev2-'),('dev-continuity','dev2-'),('shared','v2-'),('free-1','v2-'),('free-2','v2-')]:
 for path in (r/directory).glob(prefix+'*.json'):
  row=json.loads(path.read_text());recorded+=len(row['turns']);failed+=row['status']=='failed'
assert recorded==173 and failed==1
assert after['requests']-before['requests']==recorded+failed
budget={'guarded_request_attempts':after['requests']-before['requests'],
        'successful_recorded_model_calls':recorded,'failed_cases':failed,
        'reservation_delta_cny':str(Decimal(after['reserved_cny'])-Decimal(before['reserved_cny'])),
        'reserved_after_cny':after['reserved_cny'],'limit_cny':after['limit_cny'],'actual_bill':None}
(r/'budget-check.json').write_text(json.dumps(budget,ensure_ascii=False,indent=2))
(r/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
