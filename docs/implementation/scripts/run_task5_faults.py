"""Run controlled fault scenarios in the disposable task-5 database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def summarize(rows):
    costs = [r.get('cost') for r in rows]
    manual = [r['resume_seconds'] for r in rows if 'resume_seconds' in r]
    automatic = [r['seconds'] for r in rows if r.get('scenario') in {'transient', 'write_response_lost'}]
    return {'runs': len(rows), 'completion_rate': sum(r['status'] == 'succeeded' for r in rows) / len(rows),
            'duplicate_side_effects': sum(r['duplicates'] for r in rows),
            'mean_seconds': sum(r['seconds'] for r in rows) / len(rows),
            'extra_cost': None if any(c is None for c in costs) else sum(costs),
            'manual_resume_mean_seconds': sum(manual) / len(manual) if manual else None,
            'automatic_retry_mean_end_to_end_seconds': sum(automatic) / len(automatic) if automatic else None,
            'extra_model_tokens': 0, 'model_calls': 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--code-sha', required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()
    env = {**os.environ, 'TASK5_FAULT_OUTPUT': str(output / 'scenarios.json')}
    runner = Path(__file__).with_name('run_task5_tests.py')
    command = [sys.executable, str(runner), 'application.tests_tool_recovery_report']
    with (output / 'tests.txt').open('w') as log:
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SystemExit(result.returncode)
    rows = json.loads((output / 'scenarios.json').read_text())
    root = runner.resolve().parents[3]
    digest = hashlib.sha256()
    for path in sorted((root / 'apps/application/tool_recovery').glob('*.py')):
        digest.update(path.name.encode() + path.read_bytes())
    report = {'code_sha': args.code_sha, 'recovery_source_sha256': digest.hexdigest(),
              'scope': 'controlled tools; no external model calls or billable tool service',
              'summary': summarize(rows), 'scenarios': rows}
    (output / 'report.json').write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
