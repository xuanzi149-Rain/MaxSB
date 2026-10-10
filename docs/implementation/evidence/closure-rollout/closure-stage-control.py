"""Operate the local 8084 acceptance instance with an isolated database."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path('/tmp/maxsb-closure-staging')
DB = 'maxsb_task4_staging'
OPS = ROOT / 'docs/implementation/evidence/closure-rollout'
BACKUP = Path('/opt/maxkb/rollback/closure-staging/pre-evaluation.dump')
VERIFY_DB = 'maxsb_closure_backup_verify'
sys.path.insert(0, str(ROOT / 'apps'))
sys.path.insert(0, str(OPS))
os.environ['PYTHONPATH'] = str(OPS) + os.pathsep + str(ROOT / 'apps')
os.environ['MAXKB_CONFIG_TYPE'] = 'ENV'
os.environ['MAXKB_DB_NAME'] = DB
os.environ['MAXKB_REDIS_DB'] = '14'
os.environ['DJANGO_SETTINGS_MODULE'] = 'closure_settings'
os.environ['SERVER_NAME'] = 'web'
os.environ['MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY'] = (ROOT / '.staging-secret').read_text().strip()
os.environ['MAXSB_EVALUATION_BUDGET_FILE'] = '/tmp/maxsb-eval/task1-budget.json'

import django  # noqa: E402
from django.conf import settings  # noqa: E402
assert settings.DATABASES['default']['NAME'] == DB
assert settings.CACHES['default']['BACKEND'] == 'django.core.cache.backends.locmem.LocMemCache'
django.setup()
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from ops.celery import app as celery_app  # noqa: E402
assert celery_app.conf.broker_url.endswith('/14')
celery_app.conf.update(task_always_eager=False, task_ignore_result=True)
with connection.cursor() as cursor:
    cursor.execute('SELECT current_database()')
    assert cursor.fetchone()[0] == DB


def pg_env():
    db = settings.DATABASES['default']
    return {**os.environ, 'PGHOST': str(db['HOST']), 'PGPORT': str(db['PORT']),
            'PGUSER': str(db['USER']), 'PGPASSWORD': str(db['PASSWORD'])}


def table_digest(conn, name):
    from psycopg import sql
    rows = conn.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY 1').format(sql.Identifier(name))).fetchall()
    return {'rows': len(rows), 'sha256': hashlib.sha256(json.dumps(rows).encode()).hexdigest()}


def snapshot(conn):
    names = ('application', 'application_chat', 'application_chat_record',
             'application_conversation_memory', 'application_conversation_memory_event',
             'application_tool_run', 'application_tool_step', 'application_tool_attempt')
    return {name: table_digest(conn, name) for name in names}


def backup_and_migrate():
    import psycopg
    from psycopg import sql
    params = connection.get_connection_params()
    with psycopg.connect(**params) as current:
        before = snapshot(current)
        assert current.execute("SELECT to_regclass('public.application_evaluation_run')").fetchone()[0] is None
    BACKUP.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with BACKUP.open('xb') as file:
        os.chmod(BACKUP, 0o600)
        subprocess.run(['pg_dump', '-Fc', '--no-owner', '--dbname', DB], env=pg_env(), stdout=file, check=True)
    with psycopg.connect(**{**params, 'dbname': 'postgres'}, autocommit=True) as admin:
        assert not admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', [VERIFY_DB]).fetchone()
        admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(VERIFY_DB)))
        try:
            subprocess.run(['pg_restore', '--exit-on-error', '--no-owner', '--dbname', VERIFY_DB, str(BACKUP)],
                           env=pg_env(), check=True)
            with psycopg.connect(**{**params, 'dbname': VERIFY_DB}) as restored:
                assert snapshot(restored) == before
        finally:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(VERIFY_DB)))
    call_command('migrate', 'application', '0018_merge_evaluation', interactive=False, verbosity=1)
    with psycopg.connect(**params) as current:
        assert snapshot(current) == before
        assert current.execute("SELECT to_regclass('public.application_evaluation_run')").fetchone()[0]
    print(json.dumps({'database': DB, 'backup': str(BACKUP), 'restore_verified': True,
                      'existing_rows_unchanged': True, 'migration': '0018_merge_evaluation'}))


def status():
    from application.models import EvaluationRun, ToolRun
    print(json.dumps({'database': DB, 'evaluation_runs': EvaluationRun.objects.count(),
                      'tool_runs': ToolRun.objects.count(), 'source': str(ROOT)}))


def serve():
    release = json.loads((ROOT / 'release.json').read_text())
    assert len(release['commit']) == 40 and release['image_id'].startswith('sha256:')
    os.environ['MAXSB_CODE_SHA'] = release['commit']
    os.environ['MAXSB_IMAGE_ID'] = release['image_id']
    from application.evaluation.budget import install_budget_guard
    install_budget_guard()
    from django.core.wsgi import get_wsgi_application
    from django.core.servers.basehttp import ThreadedWSGIServer, WSGIRequestHandler
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    server = ThreadedWSGIServer(('127.0.0.1', 18084), WSGIRequestHandler)
    server.set_app(get_wsgi_application())
    Path('/tmp/closure-stage-server.pid').write_text(str(os.getpid()))
    try:
        print('READY closure staging 18084', flush=True)
        server.serve_forever()
    finally:
        server.server_close()


def worker():
    release = json.loads((ROOT / 'release.json').read_text())
    os.environ['MAXSB_CODE_SHA'] = release['commit']
    os.environ['MAXSB_IMAGE_ID'] = release['image_id']
    from celery.signals import worker_ready, worker_shutdown
    from ops.celery import signal_handler
    worker_ready.disconnect(signal_handler.on_app_ready)
    worker_shutdown.disconnect(signal_handler.after_app_shutdown_periodic_tasks)
    celery_app.worker_main(['worker', '--loglevel=ERROR', '--pool=solo', '--concurrency=1',
                            '--queues=celery', '--hostname=closure-evaluation@%h'])


if __name__ == '__main__':
    {'prepare': backup_and_migrate, 'status': status, 'serve': serve, 'worker': worker}[sys.argv[1]]()
