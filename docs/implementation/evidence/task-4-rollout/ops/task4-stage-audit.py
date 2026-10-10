"""Verify a staging backup in a new disposable DB; inspect business DB read-only."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import psycopg
from psycopg import sql

control = runpy.run_path('/tmp/task4-stage-control.py', run_name='inspection')
connection = control['connection']
before = control['status']()
dump = Path('/opt/maxkb/rollback/task4-staging/post-smoke.dump')
assert dump.is_file()
params = connection.get_connection_params()
params['dbname'] = 'postgres'
restore_name = control['RESTORE_DB']
with psycopg.connect(**params, autocommit=True) as admin:
    assert not admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', [restore_name]).fetchone()
    admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(restore_name)))
    try:
        subprocess.run(['pg_restore', '--exit-on-error', '--no-owner', '--dbname', restore_name, str(dump)],
                       env=control['pg_env'](), check=True)
        with psycopg.connect(**{**params, 'dbname': restore_name}) as restored:
            restored_states = restored.execute('SELECT chat_id, version, generation, facts FROM application_conversation_memory ORDER BY chat_id').fetchall()
            expected = sorted([(str(s['chat_id']), s['version'], s['generation'], s['facts']) for s in before['memory_states']])
            actual = [(str(row[0]), row[1], row[2], json.loads(row[3]) if isinstance(row[3], str) else row[3])
                      for row in restored_states]
            if expected != actual:
                print(json.dumps({'expected': expected, 'actual': actual}, ensure_ascii=False, default=str), flush=True)
            assert expected == actual
            assert restored.execute('SELECT count(*) FROM application_conversation_memory_event').fetchone()[0] == before['events']
    finally:
        admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(restore_name)))
with psycopg.connect(**{**params, 'dbname': 'maxkb'}) as business:
    migration_count = business.execute("SELECT count(*) FROM django_migrations WHERE app='application' AND name='0016_conversation_memory'").fetchone()[0]
    tables = business.execute("SELECT to_regclass('public.application_conversation_memory'), to_regclass('public.application_conversation_memory_event')").fetchone()
    assert migration_count == 0 and tables == (None, None)
    assert business.execute("SELECT count(*) FROM application WHERE name='任务4内测应用'").fetchone()[0] == 0
result = {'staging': before, 'post_smoke_backup': str(dump), 'restore_matches_memory_and_events': True,
          'business_memory_migration_count': migration_count, 'business_memory_tables': tables,
          'business_staging_apps': 0}
Path('/tmp/task4-stage-final-audit.json').write_text(json.dumps(result, ensure_ascii=False, default=str, indent=2))
print(json.dumps({'backup_restore_verified': True, 'business_database_untouched': True,
                  'enabled': before['memory_enabled'], 'memories': before['memories'], 'events': before['events']}))
sys.stdout.flush()
os._exit(0)
