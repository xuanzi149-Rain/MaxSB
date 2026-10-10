"""Task-2 paired context processing acceptance on task-1's sealed data and shared budget.

This toggles only task-2 context processing; task-3 retrieval and dialogue controls remain off.
It does not alter applications, publish workflows, or claim HTTP/workflow-engine coverage.
Tool cases are marked not applicable. Human correctness/citation review remains explicit.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'apps'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), default=str).encode()).hexdigest()


def load_helper(root, name):
    spec = importlib.util.spec_from_file_location('task1_' + name, root / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-dir', type=Path, required=True)
    parser.add_argument('--evaluation-module', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--split', choices=['dev-v1', 'frozen-v1', 'dev-v2', 'acceptance-v2'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--retrieval-only', action='store_true', help='Local embedding only; blocks external HTTP')
    parser.add_argument('--max-cases', type=int, help='Dev smoke only; forbidden on frozen data')
    parser.add_argument('--history-mode', choices=['free', 'shared'], default='free')

    parser.add_argument('--strategy-order', choices=['fixed-first', 'dynamic-first'], default='fixed-first')
    args = parser.parse_args()
    if args.max_cases is not None and (not args.split.startswith('dev-') or args.max_cases < 1):
        parser.error('Only development smoke runs may limit the cases')
    if not args.retrieval_only and not os.environ.get('MAXSB_EVALUATION_BUDGET_FILE'):
        parser.error('Existing shared evaluation budget is required')
    args.output.mkdir(parents=True, exist_ok=False)
    dataset = json.loads((args.dataset_dir / (args.split + '.json')).read_text())
    manifest = json.loads((args.dataset_dir / 'manifest.json').read_text())
    corpus = json.loads((args.dataset_dir / 'corpus.json').read_text())
    if digest(dataset) != manifest['datasets'][args.split] or digest(corpus) != manifest['corpus_hash']:
        raise ValueError('Sealed input changed')
    load_helper(args.evaluation_module, 'dataset').validate_dataset(dataset, corpus)
    score = load_helper(args.evaluation_module, 'scoring').score_case
    if args.retrieval_only:
        import httpx
        import requests
        from urllib.parse import urlparse
        def local_only(original):
            def send(client, request, **kwargs):
                if urlparse(str(request.url)).hostname not in ('localhost', '127.0.0.1', '::1'):
                    raise ValueError('External HTTP blocked in retrieval-only mode')
                return original(client, request, **kwargs)
            return send
        httpx.Client.send = local_only(httpx.Client.send)
        requests.Session.send = local_only(requests.Session.send)
    else:
        load_helper(args.evaluation_module, 'budget').install_budget_guard()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maxkb.settings')
    import django
    django.setup()
    from django.conf import settings
    settings.CELERY_BROKER_URL = 'memory://'
    from application.models import Application
    from application.flow.step_node.search_knowledge_node.impl.base_search_knowledge_node import BaseSearchKnowledgeNode
    from application.retrieval.report import summarize_pairs
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from models_provider.models import Model
    from models_provider.tools import get_model_instance_by_model_workspace_id
    from knowledge.models import Paragraph

    baseline = json.loads(args.baseline.read_text())['snapshot']
    app = Application.objects.get(pk=baseline['application_id'])
    model = Model.objects.get(pk=app.model_id)
    if model.model_name != 'qwen3.7-plus':
        raise ValueError('Budget permits only the configured task-1 model')
    params = {'extra_body': {'enable_thinking': False}, 'max_tokens': 2048,
              'max_retries': 0, 'temperature': 0, 'stream_usage': True}
    model_instance = None if args.retrieval_only else get_model_instance_by_model_workspace_id(
        str(model.pk), app.workspace_id, **params)
    knowledge_ids = baseline['knowledge_ids']
    def knowledge_hash():
        return digest(list(Paragraph.objects.filter(knowledge_id__in=knowledge_ids).order_by('id')
                           .values('id', 'content', 'title', 'is_active', 'update_time')))
    source = {}
    for folder in ('apps/application/retrieval', 'apps/application/context',
                   'apps/application/flow/step_node/search_knowledge_node',
                   'apps/application/flow/step_node/reranker_node',
                   'apps/application/flow/step_node/ai_chat_step_node'):
        for path in sorted((ROOT / folder).rglob('*.py')):
            source[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    config = {'top_n': 5, 'similarity': .2, 'search_mode': 'embedding', 'max_paragraph_char_number': 5000,
              'context_policy': {'enabled': True, 'token_budget': 2048, 'similarity_threshold': .95}}
    prompt = app.model_setting.get('prompt') or '资料：{data}\n问题：{question}'
    system = app.model_setting.get('system') or ''
    snapshot = {'utc': datetime.now(timezone.utc).isoformat(), 'dataset_hash': digest(dataset),
                'corpus_hash': digest(corpus), 'knowledge_hash': knowledge_hash(), 'source_files': source,
                'model_id': str(model.pk), 'model_alias': model.model_name, 'model_revision': str(model.update_time),
                'model_params': params, 'knowledge_ids': knowledge_ids, 'workspace': app.workspace_id,
                'prompt': prompt, 'system': system, 'dialogue_number': app.dialogue_number,
                'settings': config, 'actual_cost': None,
                'scope': 'task2 context off/on on production search node + real model; retrieval/dialogue policies off; tools excluded',
                'retrieval_only': args.retrieval_only, 'history_mode': args.history_mode,
                'dialogue_policy': False, 'strategy_order': args.strategy_order,
                'human_review': 'pending', 'historical_baseline_comparable': False,
                'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.output / 'snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    selected = dataset['cases'][:args.max_cases] if args.max_cases else dataset['cases']
    results = []
    for case in selected:
        for enabled in ((False, True) if args.strategy_order == 'fixed-first' else (True, False)):
            result = {'case_id': case['case_id'], 'scenario': case['scenario'], 'enabled': enabled,
                      'category': 'unknown', 'turns': [], 'actual_cost': None,
                      'status': 'success', 'answer': '', 'retrieved_evidence_ids': []}
            started = perf_counter()
            if case['scenario'].startswith('tool_'):
                result['status'] = 'not_applicable'
            else:
                history = []
                evidence = set()
                try:
                    for turn_index, question in enumerate(case['turns']):
                        node = BaseSearchKnowledgeNode.__new__(BaseSearchKnowledgeNode)
                        node.context = {}
                        node.workflow_manage = SimpleNamespace(get_body=lambda: {
                            'workspace_id': app.workspace_id, 'chat_user_type': 'PLATFORM_USER'})
                        current = deepcopy(config)
                        current['retrieval_policy'] = {'enabled': False}
                        current['context_policy']['enabled'] = enabled
                        current['context_policy']['semantic_enabled'] = enabled
                        retrieval_started = perf_counter()
                        output = node.execute(knowledge_ids, current, question, True,
                                              'custom', 'knowledge', []).node_variable
                        elapsed = (perf_counter() - retrieval_started) * 1000
                        human = HumanMessage(content=prompt.replace('{data}', output['data'])
                                             .replace('{question}', question))
                        messages = ([SystemMessage(content=system)] if system else [])
                        if app.dialogue_number:
                            if args.history_mode == 'shared':
                                answers = case.get('reference_answers')
                                if not isinstance(answers, list) or len(answers) != len(case['turns']):
                                    raise ValueError('Shared history requires sealed canonical reference answers')
                                for index in range(max(0, turn_index - app.dialogue_number), turn_index):
                                    messages += [HumanMessage(case['turns'][index]), AIMessage(answers[index])]
                            else:
                                messages += history[-2 * app.dialogue_number:]
                        messages.append(human)
                        response = model_instance.invoke(messages) if model_instance is not None else None
                        usage = (response.usage_metadata or {}) if response is not None else {}
                        if response is not None:
                            history += [human, response]
                        for row in output['paragraph_list']:
                            evidence.update(re.findall(r'\[((?:D|F)-[a-z-]+)\]', row['content']))
                        result['turns'].append({'question': question,
                                                'answer': response.content if response is not None else '',
                                                'input_tokens': usage.get('input_tokens'),
                                                'output_tokens': usage.get('output_tokens'),
                                                'retrieval_ms': elapsed, 'trace': output,
                                                'model_input': [m.content for m in messages]})
                    result['answer'] = result['turns'][-1]['answer']
                    result['retrieved_evidence_ids'] = sorted(evidence)
                    if args.retrieval_only:
                        result['status'] = 'retrieval_only'
                except Exception as exc:
                    result.update(status='failed', error=type(exc).__name__)
            result['elapsed_ms'] = (perf_counter() - started) * 1000
            for field in ('input_tokens', 'output_tokens'):
                values = [t[field] for t in result['turns']]
                result[field] = sum(values) if values and all(v is not None for v in values) else None
            result['score'] = score(case, result)
            if args.retrieval_only:
                result['score']['fact_mentions'] = None
            results.append(result)
            label = 'on' if enabled else 'off'
            (args.output / f"{case['case_id']}-{label}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2, default=str))
            print(json.dumps({'case': case['case_id'], 'strategy': label, 'status': result['status']}), flush=True)
    (args.output / 'summary.json').write_text(json.dumps(summarize_pairs(results), ensure_ascii=False, indent=2))
    (args.output / 'scenario-summary.json').write_text(json.dumps(
        summarize_pairs(results, group_by='scenario'), ensure_ascii=False, indent=2))
    (args.output / 'completion.json').write_text(json.dumps({
        'knowledge_unchanged': snapshot['knowledge_hash'] == knowledge_hash(), 'cases': len(selected),
        'finished': datetime.now(timezone.utc).isoformat()}))


if __name__ == '__main__':
    main()
