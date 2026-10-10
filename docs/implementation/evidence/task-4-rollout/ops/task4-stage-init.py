"""Disposable PostgreSQL + real Django HTTP/workflow; synthetic conversations only."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path('/tmp/maxsb-task4-staging')
(ROOT / 'tmp').mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / 'apps'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maxkb.settings')
os.environ.setdefault('SERVER_NAME', 'web')
os.environ['MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY'] = uuid4().hex
import django

def main():
    from django.conf import settings
    # The project pool caches by alias, so switching NAME after a read can retain the old database.
    # Use Django direct connections for this disposable acceptance process only.
    settings.DATABASES['default']['ENGINE'] = 'django.db.backends.postgresql'
    settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                   'LOCATION': 'task4-followup-http'}}
    django.setup()
    from django.db import connection
    from django.test.utils import get_runner
    from application.models import Application, ApplicationAccessToken
    from models_provider.models import Model
    baseline = json.loads(Path('/tmp/maxsb-eval/task1-results/sealed-v1/frozen-baseline.json').read_text())
    source = Application.objects.get(pk=baseline['snapshot']['application_id'])
    model_data = Model.objects.filter(pk=source.model_id).values().get()
    if model_data['model_name'] != 'qwen3.7-plus':
        raise ValueError('Only the approved model is allowed')
    # Decrypt only in memory, then encrypt with the disposable database's own key.
    from common.utils.rsa_util import rsa_long_decrypt, rsa_long_encrypt
    from system_manage.models import SystemSetting, SettingType
    source_key = SystemSetting.objects.get(type=SettingType.RSA.value).meta['value']
    credential = rsa_long_decrypt(model_data['credential'], pri_key=source_key)
    del source_key
    from ops.celery import app as celery_app
    celery_app.conf.update(broker_url='memory://', result_backend='cache+memory://',
                           task_always_eager=True, task_ignore_result=True)
    # Never enqueue acceptance tasks on the service broker.
    output = ROOT / ('followup-http-' + uuid4().hex[:8])
    output.mkdir(exist_ok=False)
    settings.DATABASES['default']['TEST']['NAME'] = 'maxsb_task4_staging'
    settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                   'LOCATION': 'task4-followup-http'}}
    settings.ALLOWED_HOSTS = ['*']
    settings.DEBUG = False
    original_create = connection.creation._create_test_db
    def create(*args, **kwargs):
        import psycopg
        name = original_create(*args, **kwargs)
        params = connection.get_connection_params()
        params['dbname'] = 'maxsb_task4_staging'
        with psycopg.connect(**params, autocommit=True) as db:
            db.execute('CREATE EXTENSION IF NOT EXISTS vector')
        return name
    connection.creation._create_test_db = create
    runner = get_runner(settings)(verbosity=1, interactive=False)
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', ['maxsb_task4_staging'])
        if cursor.fetchone():
            raise RuntimeError('Staging database already exists; refuse to overwrite')
    old_config = runner.setup_databases()
    try:
        if connection.settings_dict['NAME'] != 'maxsb_task4_staging':
            raise RuntimeError('Isolation guard failed')
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_database()')
            if cursor.fetchone()[0] != 'maxsb_task4_staging':
                raise RuntimeError('Physical database isolation guard failed')
        from users.models import User
        from application.models.application import ApplicationFolder
        from application.serializers.application import ApplicationOperateSerializer
        owner = User.objects.first()
        if owner is None:
            raise RuntimeError('Test admin fixture missing')
        model_data['user_id'] = owner.id
        model_data['credential'] = rsa_long_encrypt(credential)
        del credential
        model = Model.objects.create(**model_data)
        ApplicationFolder.objects.get_or_create(id='default', defaults={'name': 'Test'})
        flow = json.loads((ROOT / 'apps/application/flow/default_workflow.json').read_text())
        base, start = flow['nodes'][:2]
        base['properties'].update(user_input_field_list=[], api_input_field_list=[])
        base['properties']['node_data'].update(name='任务4内测应用', prologue='仅用于虚构测试数据。')
        ai = next(n for n in flow['nodes'] if n['type'] == 'ai-chat-node')
        ai['id'] = 'memory-ai'
        ai['properties']['node_data'] = {
            'model_id': str(model.id), 'model_id_type': 'custom', 'system': '简洁回答，只根据用户明确条件；未知就澄清。',
            'prompt': '{{开始.question}}', 'dialogue_number': 3, 'dialogue_type': 'WORKFLOW',
            'is_result': True, 'memory_policy': {'enabled': False},
            'model_params_setting': {'temperature': 0, 'max_tokens': 1024, 'extra_body': {'enable_thinking': False}}}
        flow = {'nodes': [base, start, ai], 'edges': [{'id': 'start-ai', 'type': 'app-edge',
                'sourceNodeId': 'start-node', 'targetNodeId': 'memory-ai',
                'sourceAnchorId': 'start-node_right', 'targetAnchorId': 'memory-ai_left',
                'startPoint': {'x': 1, 'y': 1}, 'endPoint': {'x': 2, 'y': 1}, 'properties': {}}]}
        app = Application.objects.create(name='任务4内测应用', type='WORK_FLOW', user=owner,
                workspace_id='default', model=model, work_flow=flow)
        serializer = ApplicationOperateSerializer(data={'application_id': str(app.id),
                    'workspace_id': 'default', 'user_id': str(owner.id)})
        serializer.publish({})
        token = ApplicationAccessToken.objects.get(application=app)
        token.access_num = 10000
        token.show_exec = True
        token.save()
        spec = importlib.util.spec_from_file_location('budget_guard', '/tmp/maxsb-eval/apps/application/evaluation/budget.py')
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        os.environ['MAXSB_EVALUATION_BUDGET_FILE'] = '/tmp/maxsb-eval/task1-budget.json'
        guard.install_budget_guard()
        from django.core.wsgi import get_wsgi_application
        from django.core.servers.basehttp import ThreadedWSGIServer, WSGIRequestHandler
        server = ThreadedWSGIServer(('127.0.0.1', 18084), WSGIRequestHandler)
        server.set_app(get_wsgi_application())
        (output / 'public-fixture.json').write_text(json.dumps({'application_id': str(app.id),
            'public_access_token': token.access_token, 'database': connection.settings_dict['NAME'],
            'port': 18084, 'model': model.model_name}, ensure_ascii=False, indent=2))
        (ROOT / 'followup-http-latest.json').write_text((output / 'public-fixture.json').read_text())
        print('READY task4 isolated HTTP on 18084; fixture=' + str(output), flush=True)
        import signal
        def stop(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        server.server_close()
        print('INITIALIZED persistent staging; memory disabled', flush=True)
    finally:
        connection.close()  # Keep this isolated staging database across server restarts.

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        os._exit(0)
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
