"""Paired production AI-node probe. Debug cache only; no published application changes."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'apps'))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-dir', type=Path, required=True)
    parser.add_argument('--split', choices=['dev', 'acceptance'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget-file', type=Path, required=True)
    parser.add_argument('--evaluation-module', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads((args.dataset_dir / (args.split + '.json')).read_text())
    manifest = json.loads((args.dataset_dir / 'manifest.json').read_text())
    if manifest[args.split] != digest(cases):
        raise ValueError('Sealed data changed')
    if not args.budget_file.is_file():
        raise ValueError('Existing shared budget required')
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['MAXSB_EVALUATION_BUDGET_FILE'] = str(args.budget_file)
    spec = importlib.util.spec_from_file_location('evaluation_budget', args.evaluation_module / 'budget.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    guard.install_budget_guard()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maxkb.settings')
    import django
    django.setup()
    from django.test import override_settings
    from unittest.mock import patch
    from application.models import Application, ChatRecord
    from application.flow.step_node.ai_chat_step_node.impl.base_chat_node import BaseChatNode
    from application.conversation_memory.report import summarize
    from application.conversation_memory.temporary import TemporaryMemoryStore
    from application.conversation_memory.types import Identity
    from models_provider.tools import get_model_instance_by_model_workspace_id
    from models_provider.models import Model
    from langchain_core.messages import HumanMessage
    app = Application.objects.get(pk=json.loads(args.baseline.read_text())['snapshot']['application_id'])
    model_row = Model.objects.get(pk=app.model_id)
    if model_row.model_name != 'qwen3.7-plus':
        raise ValueError('Only the previously budgeted model is allowed')
    model = get_model_instance_by_model_workspace_id(str(model_row.id), app.workspace_id,
            extra_body={'enable_thinking': False}, max_tokens=1024, max_retries=0, temperature=0, stream_usage=True)
    if not getattr(model, 'root_client', None):
        raise ValueError('Bounded extraction adapter unavailable')
    source = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for folder in ['apps/application/conversation_memory', 'apps/application/flow/step_node/ai_chat_step_node']
              for p in (ROOT / folder).rglob('*.py')}
    snapshot = {'dataset_hash': digest(cases), 'model': model_row.model_name, 'model_revision': str(model_row.update_time),
                'model_id': str(model_row.id), 'source': source, 'history_rounds': 3, 'temperature': 0,
                'max_tokens': 1024, 'started_at': time.time(), 'kind': 'production-node-debug-cache-probe',
                'budget_before': json.loads(args.budget_file.read_text())}
    (args.output / 'snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    records = []
    system = '你是需求记录助手。只根据用户明确条件回答，不知道就澄清。闲聊和记住要求的请求只简短确认，不复述全部历史。'
    with override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}):
        for case in cases:
            for strategy in ('fixed', 'memory'):
                chat_id = str(uuid4())
                identity = Identity(str(app.id), 'task4-evaluation', 'PLATFORM_USER')
                history = []
                for index, question in enumerate(case['turns']):
                    record_id = str(uuid4())
                    row = {'case_id': case['id'], 'strategy': strategy, 'turn': index, 'question': question}
                    started = time.monotonic()
                    try:
                        if index == case.get('clear_before') and strategy == 'memory':
                            store = TemporaryMemoryStore(identity, chat_id)
                            state = store.read(identity, chat_id)
                            store.clear(identity, chat_id, state.version, str(uuid4()))
                        node = BaseChatNode.__new__(BaseChatNode)
                        node.context = {'start_time': time.time()}
                        node.runtime_node_id = 'ai'
                        node.node = SimpleNamespace(properties={'stepName': 'AI', 'node_data': {
                            'memory_policy': {'enabled': strategy == 'memory'}}}, type='ai-chat-node')
                        node.node_params_serializer = SimpleNamespace(data={})
                        node.status, node.err_message = 200, ''
                        body = {'application_id': str(app.id), 'workspace_id': app.workspace_id,
                                'chat_user_id': identity.chat_user_id, 'chat_user_type': identity.chat_user_type,
                                'debug': True}
                        manager = SimpleNamespace(get_body=lambda: body, generate_prompt=lambda value: value,
                                   flow=SimpleNamespace(nodes=[node.node], workflow_mode='application'),
                                   is_result=lambda *a: False, is_the_task_interrupted=lambda: False)
                        node.workflow_manage = manager
                        node.generate_prompt_question = lambda *a: HumanMessage(question)
                        node._handle_mcp_request = lambda *a, **k: None
                        path = 'application.flow.step_node.ai_chat_step_node.impl.base_chat_node'
                        with patch(path + '.get_model_instance_by_model_workspace_id', return_value=model), \
                             patch(path + '.filter_authorized_ids', return_value=[]):
                            result = node.execute(str(model_row.id), system, question, 3, history, False, chat_id,
                                    record_id, model_params_setting={}, memory_policy={'enabled': strategy == 'memory'},
                                    question=question)
                        result.write_context(node, manager)
                        response = result.node_variable['result']
                        row['answer'] = response.content
                        row['messages'] = [{'role': m.type, 'content': m.content}
                                           for m in result.node_variable['message_list']]
                        row['memory'] = node.context.get('memory')
                        row['usage'] = (row['memory']['total_usage'] if row['memory'] else
                                        {**(response.usage_metadata or {}), 'cost': None})
                        history.append(ChatRecord(id=record_id, problem_text=question, answer_text=response.content))
                    except Exception as exc:
                        row['error'] = type(exc).__name__
                    row['duration_seconds'] = time.monotonic() - started
                    records.append(row)
                    (args.output / 'records.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
                    print(case['id'], strategy, index, row.get('error', row.get('memory', {}).get('status', 'ok')
                          if row.get('memory') else 'ok'), flush=True)
    (args.output / 'report.json').write_text(json.dumps(summarize(records), ensure_ascii=False, indent=2))
    (args.output / 'budget-after.json').write_text(args.budget_file.read_text())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
