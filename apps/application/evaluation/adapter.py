# coding=utf-8
"""Execute the original chat engine in a disposable, bounded subprocess per case."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def execute_case(case: dict, snapshot: dict) -> dict:
    root = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix='maxsb-eval-') as directory:
        request_path = Path(directory) / 'request.json'
        response_path = Path(directory) / 'response.json'
        request_path.write_text(json.dumps({'case': case, 'snapshot': snapshot}))
        env = {**os.environ, 'PYTHONPATH': str(root / 'apps') + os.pathsep + os.environ.get('PYTHONPATH', ''), 'DJANGO_SETTINGS_MODULE': os.environ.get('DJANGO_SETTINGS_MODULE', 'maxkb.settings')}
        try:
            child = subprocess.run([sys.executable, '-m', 'application.evaluation.child', str(request_path),
                                    str(response_path)], cwd=root, env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=180)
        except subprocess.TimeoutExpired:
            return {'status': 'failed', 'error': 'case_timeout', 'answer': '', 'actual_cost': None,
                    'input_tokens': None, 'output_tokens': None}
        if child.returncode != 0 or not response_path.exists():
            return {'status': 'failed', 'error': 'chat_process_failed', 'answer': '', 'actual_cost': None}
        return json.loads(response_path.read_text())
