"""Run six groups serially, preserving outputs and stopping on infrastructure errors."""
import subprocess,sys,json
from pathlib import Path
root=Path('/tmp/maxsb-task6-staging')
for split in ('dev-v1','frozen-v1'):
    for role in ('low','high','routing'):
        result=subprocess.run([sys.executable,'-u','/tmp/task6-run.py',split,role],cwd=root)
        if result.returncode:
            raise SystemExit(result.returncode)
        data=json.loads((root/'formal'/f'{split}-{role}.json').read_text())
        faults=[r.get('error') for r in data['cases'] if r.get('error') in ('chat_process_failed','configuration_drift','case_timeout')]
        if faults:
            print(json.dumps({'event':'stopped','infrastructure_errors':faults}),flush=True)
            raise SystemExit(2)
print(json.dumps({'event':'all_six_groups_complete'}),flush=True)
