"""Run each sealed split/group once, with shared budget and immutable result files."""
import runpy, json, os, sys
from pathlib import Path
scope=runpy.run_path('/tmp/task6-stage-control.py')
from application.evaluation.dataset import dataset_digest, validate_dataset
from application.evaluation.service import create_run, execute_run
from application.evaluation.metrics import summarize
from application.models import Application, EvaluationRun
from django.core.serializers.json import DjangoJSONEncoder
root=scope['ROOT']; fixture=json.loads((root/'task6-fixture.json').read_text())
out=root/'formal'; out.mkdir(exist_ok=True)
version,role=sys.argv[1:]
assert version in ('dev-v1','frozen-v1') and role in ('low','high','routing')
data_root=root/'docs/implementation/evaluation'
dataset=json.loads((data_root/(version+'.json')).read_text()); corpus=json.loads((data_root/'corpus.json').read_text()); manifest=json.loads((data_root/'manifest.json').read_text())
validate_dataset(dataset,corpus)
assert dataset_digest(dataset)==manifest['datasets'][version] and dataset_digest(corpus)==manifest['corpus_hash']
assert manifest['rubric_review']['status']=='reviewed'
assert json.loads((data_root/'task6-protocol.json').read_text())['status']=='ready'
path=out/(version+'-'+role+'.json')
with path.open('x') as f: json.dump({'state':'reserved'},f)
app=Application.objects.get(pk=fixture['application_id'])
run=create_run(app.workspace_id,str(app.pk),fixture['user_id'],dataset,enqueue=False,routing_strategy=role)
assert all(run.snapshot[k] for k in ('code_sha','local_diff_hash','evaluation_source_hash','routing_protocol_hash'))
path.write_text(json.dumps({'state':'started','run_id':str(run.pk)})); print(json.dumps({'event':'start','dataset':version,'role':role,'run_id':str(run.pk)}),flush=True)
execute_run(str(run.pk)); run.refresh_from_db()
rows=[{**r.result,'review':r.review} for r in run.results.order_by('case_id')]
data={'run_id':str(run.pk),'status':run.status,'dataset_version':run.dataset['version'],'dataset_hash':run.dataset_hash,'config_hash':run.snapshot['config_hash'],'created_at':run.create_time,'started_at':run.started_at,'finished_at':run.finished_at,'progress':len(rows),'total':len(dataset['cases']),'summary':summarize(rows,total_cases=len(dataset['cases'])),'error':run.error,'snapshot':{k:v for k,v in run.snapshot.items() if k not in ('user_id','application_config')},'cases':rows,'questions':dataset['cases']}
path.write_text(json.dumps(data,cls=DjangoJSONEncoder,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'event':'finish','dataset':version,'role':role,'status':run.status,'cases':len(rows),'successful':sum(r['status']=='success' for r in rows)}),flush=True)
scope['connection'].close();sys.stdout.flush();os._exit(0 if run.status=='completed' else 1)
