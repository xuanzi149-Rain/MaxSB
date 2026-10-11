import runpy,json,os,sys
s=runpy.run_path('/tmp/task6-stage-control.py')
from application.models import EvaluationRun
from django.db.models import Count
f=json.loads((s['ROOT']/'task6-fixture.json').read_text())
for run in EvaluationRun.objects.filter(application_id=f['application_id']).order_by('create_time'):
 print(json.dumps({'run_id':str(run.id),'split':run.dataset.get('split'),'role':run.snapshot.get('routing_strategy'),'status':run.status,'total':len(run.dataset['cases']),'results':list(run.results.values('status','result__error').annotate(count=Count('id')))}))
b=json.loads(open('/tmp/task6-live-smoke-01/budget.json').read())
print(json.dumps({'budget_limit':b['limit_cny'],'reserved_cny':b['reserved_cny'],'requests':b['requests']}))
s['connection'].close();sys.stdout.flush();os._exit(0)
