"""Preserve the incomplete run; never silently resume or overwrite its cases."""
import runpy,json,os,sys
s=runpy.run_path('/tmp/task6-stage-control.py')
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
from application.models import EvaluationRun
from application.evaluation.metrics import summarize
run=EvaluationRun.objects.get(pk='c6f5600e-8bb9-4349-b39c-58186a4fcd69')
assert run.status in ('running','interrupted')
run.status='interrupted';run.error='container_oom';run.finished_at=timezone.now()
rows=[{**r.result,'review':r.review} for r in run.results.order_by('case_id')]
run.summary=summarize(rows,total_cases=len(run.dataset['cases']));run.save(update_fields=['status','error','finished_at','summary','update_time'])
out=s['ROOT']/'formal'; old=out/'dev-v1-low.json'; backup=out/'dev-v1-low-interrupted-01.json'
assert not backup.exists()
data={'run_id':str(run.pk),'status':run.status,'error':run.error,'progress':len(rows),'total':len(run.dataset['cases']),'dataset_hash':run.dataset_hash,'config_hash':run.snapshot['config_hash'],'snapshot':{k:v for k,v in run.snapshot.items() if k not in ('user_id','application_config')},'cases':rows,'summary':run.summary}
backup.write_text(json.dumps(data,cls=DjangoJSONEncoder,ensure_ascii=False,indent=2)+'\n')
assert json.loads(old.read_text())['run_id']==str(run.pk)
old.rename(out/'dev-v1-low-interrupted-01-start.json')
print(json.dumps({'preserved_run':str(run.pk),'cases':len(rows),'reason':'container_oom'}))
s['connection'].close();sys.stdout.flush();os._exit(0)
