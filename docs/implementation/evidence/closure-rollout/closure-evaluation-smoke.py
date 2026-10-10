"""Run one sealed, read-only tool case through the isolated evaluation worker."""
import json
import os
from pathlib import Path
import runpy
import time

scope = runpy.run_path('/tmp/closure-stage-control.py', run_name='smoke')
from application.evaluation.service import create_run  # noqa: E402
from application.models import Application, EvaluationRun  # noqa: E402

root = scope['ROOT']
release = json.loads((root / 'release.json').read_text())
os.environ['MAXSB_CODE_SHA'] = release['commit']
os.environ['MAXSB_IMAGE_ID'] = release['image_id']
cases = json.loads((root / 'docs/implementation/evaluation/dev-v1.json').read_text())['cases']
case = next(case for case in cases if case['case_id'] == 'dev-14' and case['scenario'] == 'tool_success')
application = Application.objects.get(name='任务5部署验证', workspace_id='default')
run = create_run('default', str(application.id), str(application.user_id),
                 {'version': 'closure-smoke', 'cases': [case]})
assert run.snapshot['code_sha'] == release['commit']
assert run.snapshot['image_id'] == release['image_id']
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    run.refresh_from_db()
    if run.status not in ('queued', 'running'):
        break
    time.sleep(1)
assert run.status == 'completed', (run.status, run.error)
row = run.results.get(case_id=case['case_id'])
assert row.status == 'success', row.result.get('error')
assert row.result['input_tokens'] == row.result['output_tokens'] == 0
print(json.dumps({'run_id': str(run.id), 'status': run.status, 'case_id': case['case_id'],
                  'case_status': row.status, 'code_sha': run.snapshot['code_sha'],
                  'image_id': run.snapshot['image_id'], 'model_calls': 0}))
