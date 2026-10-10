"""Verify historical rows, business isolation, and retire the synthetic probe access."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import psycopg
from psycopg import sql
scope=runpy.run_path('/tmp/task5-stage-control.py',run_name='stage_operations')
root=scope['ROOT']
original=json.loads((root/'followup-http-latest.json').read_text())['application_id']
probe=json.loads((root/'task5-private-fixture.json').read_text())['application_id']
before=json.loads((root/'deploy-prepare.json').read_text())['before']
conditions={
 'application':('id=%s',[original]),
 'application_chat':('application_id=%s',[original]),
 'application_chat_record':('chat_id IN (SELECT id FROM application_chat WHERE application_id=%s)',[original]),
 'application_conversation_memory':('TRUE',[]),
 'application_conversation_memory_event':('TRUE',[]),
}
params=scope['connection'].get_connection_params()
with psycopg.connect(**params) as conn:
    for table,(where,args) in conditions.items():
        rows=conn.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t WHERE '+where+' ORDER BY 1').format(sql.Identifier(table)),args).fetchall()
        got={'count':len(rows),'sha256':hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
        assert got==before[table], table
with psycopg.connect(**{**params,'dbname':'maxkb'}) as business:
    assert business.execute("SELECT to_regclass('public.application_tool_run')").fetchone()[0] is None
    assert not business.execute("SELECT 1 FROM django_migrations WHERE app='application' AND name='0017_tool_recovery'").fetchone()
from application.models import ApplicationAccessToken, ToolRun
ApplicationAccessToken.objects.filter(application_id=probe).update(is_active=False)
result={'historical_data_unchanged':True,'business_database_unchanged':True,'probe_access_disabled':True,
        'persisted_probe_runs':ToolRun.objects.filter(chat__application_id=probe).count(),'sandbox':1}
(root/'deploy-audit.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
scope['connection'].close()
sys.stdout.flush()
os._exit(0)
