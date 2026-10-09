"""Two bounded HTTP smoke calls against the dedicated, synthetic local demo only."""
import importlib.util
import json
import logging
import os
from pathlib import Path
import time
import requests



def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maxkb.settings')
    import django
    django.setup()
    logging.disable(logging.CRITICAL)
    from application.models import Application, ApplicationAccessToken, ChatRecord
    from application.serializers.application import ApplicationOperateSerializer

    app = Application.objects.get(name='任务2同义去重验证', workspace_id='default')
    resources = json.loads(Path('/opt/maxkb/task2-online-demo/resources.json').read_text())
    if str(app.pk) != resources['application_id']:
        raise ValueError('dedicated demo mismatch')
    token = ApplicationAccessToken.objects.get(application=app)
    spec = importlib.util.spec_from_file_location('approved_budget',
                '/tmp/maxsb-task2-semantic/apps/application/evaluation/budget.py')
    budget = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(budget)
    session = requests.Session()
    session.trust_env = False
    base = 'http://127.0.0.1:8080/chat/api'
    response = session.post(base + '/auth/anonymous', json={'access_token': token.access_token}, timeout=20)
    response.raise_for_status()
    auth = response.json()
    if auth['code'] != 200:
        raise ValueError('demo authentication failed')
    session.headers['Authorization'] = 'Bearer ' + auth['data']
    records = []

    def publish(enabled):
        app.knowledge_setting = {**app.knowledge_setting, 'context_policy': {
            'enabled': enabled, 'semantic_enabled': enabled, 'token_budget': 2048, 'similarity_threshold': .95}}
        app.save(update_fields=['knowledge_setting'])
        ApplicationOperateSerializer(data={'application_id': str(app.pk), 'workspace_id': app.workspace_id,
                                           'user_id': str(app.user_id)}).publish({})
    try:
        for enabled in (False, True):
            publish(enabled)
            opened = session.get(base + '/open', timeout=20)
            opened.raise_for_status()
            payload = opened.json()
            if payload['code'] != 200:
                raise ValueError('demo chat could not open')
            chat_id = payload['data']
            budget.reserve_request('/tmp/maxsb-eval/task1-budget.json', {
                'model': 'qwen3.7-plus', 'enable_thinking': False, 'max_tokens': 2048,
                'messages': [{'role': 'user', 'content': '测' * 6000}]})
            started = time.monotonic()
            result = session.post(base + '/chat_message/' + chat_id,
                json={'message': '阅览室可以吸烟吗？', 'stream': False, 're_chat': False}, timeout=90)
            result.raise_for_status()
            if result.json()['code'] != 200:
                raise ValueError('demo answering failed')
            record = ChatRecord.objects.filter(chat_id=chat_id).order_by('-create_time').first()
            if record is None:
                raise ValueError('demo record not saved')
            audit = record.details.get('generate_human_message', {}).get('context_processing')
            row = {'policy': 'on' if enabled else 'off', 'chat_id': str(chat_id),
                   'chat_record_id': str(record.pk), 'answer': record.answer_text,
                   'input_tokens': record.message_tokens, 'output_tokens': record.answer_tokens,
                   'seconds': time.monotonic() - started, 'audit': audit,
                   'human_correct': None, 'human_citation_accuracy': None}
            records.append(row)
            Path('/opt/maxkb/task2-online-demo/http-records.json').write_text(
                json.dumps(records, ensure_ascii=False, indent=2))
            if enabled and (not audit or audit['semantic']['actual_removed_count'] != 1):
                raise ValueError('online semantic replacement did not occur')
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        publish(True)


if __name__ == '__main__':
    main()
