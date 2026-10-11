"""Deploy only the existing local acceptance database, with in-place rollback backup."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
ROOT = Path('/tmp/maxsb-task6-staging')
sys.path[:0] = [str(ROOT), str(ROOT / 'apps')]
os.environ['DJANGO_SETTINGS_MODULE'] = 'task6_stage_settings'
os.environ['SERVER_NAME'] = 'web'
os.environ.setdefault('MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY', uuid4().hex)
import django  # noqa: E402
django.setup()
from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402
DB = 'maxsb_task4_staging'
with connection.cursor() as cursor:
    cursor.execute('SELECT current_database()')
    assert cursor.fetchone()[0] == DB


def digest(db, tables=None):
    from psycopg import sql
    tables = tables or [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'application%' ORDER BY tablename")]
    result = {}
    for name in tables:
        rows = db.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY 1').format(sql.Identifier(name))).fetchall()
        result[name] = {'count': len(rows), 'sha256': hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
    return result


def prepare():
    import psycopg
    from psycopg import sql
    from django.core.management import call_command
    params = connection.get_connection_params()
    with psycopg.connect(**params) as db:
        before = digest(db)
    backup = Path('/opt/maxkb/rollback/task6-staging/pre-0019.dump')
    backup.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    conf = settings.DATABASES['default']
    env = {**os.environ, 'PGHOST': str(conf['HOST']), 'PGPORT': str(conf['PORT']),
           'PGUSER': str(conf['USER']), 'PGPASSWORD': str(conf['PASSWORD'])}
    with backup.open('xb') as handle:
        os.chmod(backup, 0o600)
        subprocess.run(['pg_dump', '-Fc', '--no-owner', '--dbname', DB], env=env, stdout=handle, check=True)
    verify = 'maxsb_task6_backup_verify'
    with psycopg.connect(**{**params, 'dbname': 'postgres'}, autocommit=True) as admin:
        assert not admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', [verify]).fetchone()
        admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(verify)))
        try:
            subprocess.run(['pg_restore', '--exit-on-error', '--no-owner', '--dbname', verify, str(backup)], env=env, check=True)
            with psycopg.connect(**{**params, 'dbname': verify}) as restored:
                assert digest(restored, before) == before
        finally:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(verify)))
    call_command('migrate', 'application', '0019_nullable_chat_usage', interactive=False, verbosity=1)
    with psycopg.connect(**params) as db:
        assert digest(db, before) == before
    report = {'database': DB, 'backup': str(backup), 'restore_verified': True, 'existing_application_data_unchanged': True,
              'before': before, 'migration': '0019_nullable_chat_usage', 'release': 'adfe3f191'}
    (ROOT / 'deploy-prepare.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


def serve():
    from application.evaluation.budget import install_budget_guard
    install_budget_guard()
    from django.core.wsgi import get_wsgi_application
    from django.core.servers.basehttp import ThreadedWSGIServer, WSGIRequestHandler
    from ops.celery import app
    app.conf.update(broker_url='memory://', result_backend='cache+memory://', task_always_eager=True, task_ignore_result=True)
    import signal
    def stop(*args):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    server = ThreadedWSGIServer(('127.0.0.1', 18084), WSGIRequestHandler)
    server.set_app(get_wsgi_application())
    Path('/tmp/task6-stage-server.pid').write_text(str(os.getpid()))
    print('READY task6 staging on 18084; cumulative budget enabled', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    code = 0
    try:
        {'prepare': prepare, 'serve': serve}[sys.argv[1]]()
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
