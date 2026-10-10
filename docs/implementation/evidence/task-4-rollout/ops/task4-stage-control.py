"""Local-only task 4 staging operations. Never targets the business database."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path('/tmp/maxsb-task4-staging')
DB = 'maxsb_task4_staging'
RESTORE_DB = 'maxsb_task4_staging_restore'
sys.path.insert(0, str(ROOT / 'apps'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maxkb.settings')
os.environ.setdefault('SERVER_NAME', 'web')
os.environ['MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY'] = uuid4().hex
import django
from django.conf import settings

settings.DATABASES['default'].update(ENGINE='django.db.backends.postgresql', NAME=DB)
settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                              'LOCATION': 'task4-staging'}}
secret_path = ROOT / '.staging-secret'
if not secret_path.exists():
    from django.core.management.utils import get_random_secret_key
    with secret_path.open('x') as secret_file:
        os.chmod(secret_path, 0o600)
        secret_file.write(get_random_secret_key())
settings.SECRET_KEY = secret_path.read_text()
settings.DEBUG = False
settings.ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
django.setup()
from django.db import connection
from django.core.management import call_command
from ops.celery import app as celery_app
celery_app.conf.update(broker_url='memory://', result_backend='cache+memory://',
                       task_always_eager=True, task_ignore_result=True)
with connection.cursor() as cursor:
    cursor.execute('SELECT current_database()')
    assert cursor.fetchone()[0] == DB, 'Physical database isolation failed'


def pg_env():
    conf = settings.DATABASES['default']
    return {**os.environ, 'PGHOST': str(conf['HOST']), 'PGPORT': str(conf['PORT']),
            'PGUSER': str(conf['USER']), 'PGPASSWORD': str(conf['PASSWORD'])}


def backup(name):
    folder = Path('/opt/maxkb/rollback/task4-staging')
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / name
    if path.exists():
        raise RuntimeError('Refuse to overwrite existing backup')
    with path.open('xb') as target:
        os.chmod(path, 0o600)
        subprocess.run(['pg_dump', '-Fc', '--no-owner', '--dbname', DB], env=pg_env(),
                       stdout=target, check=True)
    return path


def status():
    from application.models import Application, Chat, ConversationMemory, ConversationMemoryEvent
    fixture = json.loads((ROOT / 'followup-http-latest.json').read_text())
    app = Application.objects.get(pk=fixture['application_id'])
    node = next(n for n in app.work_flow['nodes'] if n['type'] == 'ai-chat-node')
    return {'database': DB, 'application_id': str(app.id),
            'memory_enabled': node['properties']['node_data']['memory_policy']['enabled'],
            'chats': Chat.objects.count(), 'memories': ConversationMemory.objects.count(),
            'events': ConversationMemoryEvent.objects.count(),
            'memory_states': list(ConversationMemory.objects.values('chat_id', 'version', 'generation', 'facts'))}


def rehearse():
    import psycopg
    from psycopg import sql
    from application.models import Chat, ConversationMemory, ConversationMemoryEvent
    assert Chat.objects.count() == ConversationMemory.objects.count() == ConversationMemoryEvent.objects.count() == 0
    call_command('migrate', 'application', '0015', interactive=False, verbosity=1)
    path = backup('pre-0016.dump')
    call_command('migrate', 'application', '0016', interactive=False, verbosity=1)
    call_command('migrate', 'application', '0015', interactive=False, verbosity=1)
    call_command('migrate', 'application', '0016', interactive=False, verbosity=1)
    params = connection.get_connection_params()
    params['dbname'] = 'postgres'
    with psycopg.connect(**params, autocommit=True) as admin:
        assert not admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', [RESTORE_DB]).fetchone()
        admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(RESTORE_DB)))
        try:
            subprocess.run(['pg_restore', '--exit-on-error', '--no-owner', '--dbname', RESTORE_DB, str(path)],
                           env=pg_env(), check=True)
            restored_params = {**params, 'dbname': RESTORE_DB}
            with psycopg.connect(**restored_params) as restored:
                assert restored.execute("SELECT count(*) FROM django_migrations WHERE app='application' AND name LIKE '0016%'").fetchone()[0] == 0
                assert restored.execute("SELECT to_regclass('public.application_conversation_memory')").fetchone()[0] is None
                assert restored.execute('SELECT count(*) FROM application').fetchone()[0] == 1
        finally:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(RESTORE_DB)))
    print(json.dumps({'backup': str(path), 'restore_verified': True, 'migration_roundtrip': True}))


def toggle(enabled):
    from application.models import Application
    from application.serializers.application import ApplicationOperateSerializer
    fixture = json.loads((ROOT / 'followup-http-latest.json').read_text())
    app = Application.objects.get(pk=fixture['application_id'])
    assert app.name == '任务4内测应用'
    for node in app.work_flow['nodes']:
        if node['type'] == 'ai-chat-node':
            node['properties']['node_data']['memory_policy']['enabled'] = enabled
    app.save(update_fields=['work_flow'])
    ApplicationOperateSerializer(data={'application_id': str(app.id), 'workspace_id': app.workspace_id,
                                      'user_id': str(app.user_id)}).publish({})
    print(json.dumps({'database': DB, 'memory_enabled': enabled}))


def serve():
    spec = importlib.util.spec_from_file_location('budget_guard', '/tmp/maxsb-eval/apps/application/evaluation/budget.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    os.environ['MAXSB_EVALUATION_BUDGET_FILE'] = '/tmp/maxsb-eval/task1-budget.json'
    guard.install_budget_guard()
    from django.core.wsgi import get_wsgi_application
    from django.core.servers.basehttp import ThreadedWSGIServer, WSGIRequestHandler
    import signal
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    server = ThreadedWSGIServer(('127.0.0.1', 18084), WSGIRequestHandler)
    server.set_app(get_wsgi_application())
    print('READY persistent staging HTTP 18084, loopback only', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    command = sys.argv[1]
    try:
        if command == 'rehearse':
            rehearse()
        elif command in {'enable', 'disable'}:
            toggle(command == 'enable')
        elif command == 'status':
            print(json.dumps(status(), ensure_ascii=False, default=str))
        elif command == 'backup':
            print(backup('post-smoke.dump'))
        elif command == 'serve':
            serve()
        else:
            raise ValueError('Unknown command')
    except KeyboardInterrupt:
        pass
    finally:
        connection.close()
    sys.stdout.flush()
    os._exit(0)
