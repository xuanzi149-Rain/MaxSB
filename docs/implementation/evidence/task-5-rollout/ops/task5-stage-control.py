"""Local staging deployment only; never migrate the business database."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path('/tmp/maxsb-task5-staging')
DB = 'maxsb_task4_staging'
BACKUP = Path('/opt/maxkb/rollback/task5-staging/pre-0017.dump')
RESTORE_DB = 'maxsb_task5_backup_verify'
sys.path.insert(0, str(ROOT / 'apps'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maxkb.settings')
os.environ.setdefault('SERVER_NAME', 'web')
os.environ['MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY'] = uuid4().hex
import django
from django.conf import settings
settings.DATABASES['default'].update(ENGINE='django.db.backends.postgresql', NAME=DB)
settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'task5-stage'}}
settings.SECRET_KEY = (ROOT / '.staging-secret').read_text()
settings.DEBUG = False
settings.ALLOWED_HOSTS = ['localhost', '127.0.0.1']
django.setup()
from django.db import connection
from django.core.management import call_command
from ops.celery import app as celery_app
celery_app.conf.update(broker_url='memory://', result_backend='cache+memory://', task_always_eager=True, task_ignore_result=True)
with connection.cursor() as cursor:
    cursor.execute('SELECT current_database()')
    assert cursor.fetchone()[0] == DB


def pg_env():
    conf = settings.DATABASES['default']
    return {**os.environ, 'PGHOST': str(conf['HOST']), 'PGPORT': str(conf['PORT']),
            'PGUSER': str(conf['USER']), 'PGPASSWORD': str(conf['PASSWORD'])}


def digest(db):
    tables = ['application', 'application_chat', 'application_chat_record',
              'application_conversation_memory', 'application_conversation_memory_event']
    result = {}
    from psycopg import sql
    for table in tables:
        rows = db.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY 1').format(sql.Identifier(table))).fetchall()
        result[table] = {'count': len(rows), 'sha256': hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
    return result


def prepare():
    import psycopg
    from psycopg import sql
    params = connection.get_connection_params()
    with psycopg.connect(**params) as current:
        before = digest(current)
        assert current.execute("SELECT to_regclass('public.application_tool_run')").fetchone()[0] is None
    BACKUP.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with BACKUP.open('xb') as out:
        os.chmod(BACKUP, 0o600)
        subprocess.run(['pg_dump', '-Fc', '--no-owner', '--dbname', DB], env=pg_env(), stdout=out, check=True)
    with psycopg.connect(**{**params, 'dbname': 'postgres'}, autocommit=True) as admin:
        assert not admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', [RESTORE_DB]).fetchone()
        admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(RESTORE_DB)))
        try:
            subprocess.run(['pg_restore', '--exit-on-error', '--no-owner', '--dbname', RESTORE_DB, str(BACKUP)],
                           env=pg_env(), check=True)
            with psycopg.connect(**{**params, 'dbname': RESTORE_DB}) as restored:
                assert digest(restored) == before
        finally:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(RESTORE_DB)))
    call_command('migrate', 'application', '0017_tool_recovery', interactive=False, verbosity=1)
    with psycopg.connect(**params) as current:
        assert digest(current) == before
        assert current.execute("SELECT to_regclass('public.application_tool_run')").fetchone()[0]
    result = {'database': DB, 'backup': str(BACKUP), 'restore_verified': True,
              'existing_data_unchanged': True, 'before': before, 'migration': '0017_tool_recovery'}
    (ROOT / 'deploy-prepare.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


def status():
    from application.models import Application, Chat, ChatRecord, ConversationMemory, ConversationMemoryEvent, ToolRun
    from maxkb.const import CONFIG
    print(json.dumps({'database': DB, 'sandbox': CONFIG.get('SANDBOX', 1),
          'applications': Application.objects.count(), 'chats': Chat.objects.count(), 'records': ChatRecord.objects.count(),
          'memories': ConversationMemory.objects.count(), 'events': ConversationMemoryEvent.objects.count(),
          'recovery_runs': ToolRun.objects.count(), 'release': 'b005600b8'}, default=str))


def serve():
    spec = importlib.util.spec_from_file_location('budget_guard', '/tmp/maxsb-eval/apps/application/evaluation/budget.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    os.environ['MAXSB_EVALUATION_BUDGET_FILE'] = '/tmp/maxsb-eval/task1-budget.json'
    guard.install_budget_guard()
    import signal
    from django.core.wsgi import get_wsgi_application
    from django.core.servers.basehttp import ThreadedWSGIServer, WSGIRequestHandler
    def stop(*args):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    server = ThreadedWSGIServer(('127.0.0.1', 18084), WSGIRequestHandler)
    server.set_app(get_wsgi_application())
    Path('/tmp/task5-stage-server.pid').write_text(str(os.getpid()))
    print('READY task5 staging 18084, sandbox unchanged', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    code = 0
    try:
        {'prepare': prepare, 'status': status, 'serve': serve}[sys.argv[1]]()
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
        code = 1
    finally:
        connection.close()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
