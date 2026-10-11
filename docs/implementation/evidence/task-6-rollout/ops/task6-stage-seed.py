"""Seed only approved models and sealed synthetic corpus in the local acceptance DB."""
import json
import os
from pathlib import Path
import runpy
import sys
scope = runpy.run_path('/tmp/task6-stage-control.py', run_name='stage_operations')
from django.conf import settings
from django.db import connection
from application.models import Application, ApplicationAccessToken
from application.serializers.application import ApplicationOperateSerializer
from models_provider.models import Model
from users.models import User
from common.utils.rsa_util import rsa_long_decrypt, rsa_long_encrypt
from common.utils.common import password_verify
from maxkb.const import CONFIG
from application.evaluation.dataset import dataset_digest
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
root = scope['ROOT']
assert not (root / 'task6-fixture.json').exists()
owner = User.objects.get(username='admin')
conf = settings.SOURCE_DATABASE
source_params = {'dbname': conf['NAME'], 'host': conf['HOST'], 'port': conf['PORT'],
                 'user': conf['USER'], 'password': conf['PASSWORD']}
assert source_params['dbname'] != scope['DB']
low, high = '01a11e76-45ee-79c1-bf92-2bb8dd5a9c42', '01a11f05-0114-7e73-859e-5cc08ccb3e70'
corpus = json.loads((root / 'docs/implementation/evaluation/corpus.json').read_text())
with psycopg.connect(**source_params, row_factory=dict_row) as source:
    source.execute('SET TRANSACTION READ ONLY')
    private_key = source.execute('SELECT meta FROM system_setting WHERE type=1').fetchone()['meta']['value']
    for identity, name in ((low, 'qwen3.7-plus'), (high, 'deepseek-v4-flash')):
        assert not Model.objects.filter(id=identity).exists()
        row = source.execute(sql.SQL('SELECT * FROM {} WHERE id=%s').format(sql.Identifier(Model._meta.db_table)), [identity]).fetchone()
        assert row and row['model_name'] == name and row['workspace_id'] == 'default' and row['status'] == 'SUCCESS'
        credential = rsa_long_decrypt(row['credential'], pri_key=private_key)
        row['credential'] = rsa_long_encrypt(credential)
        del credential
        row['user_id'] = owner.id
        Model.objects.create(**row)
    del private_key
    knowledge = source.execute('SELECT id, meta, embedding_model_id FROM knowledge WHERE name=%s', ['任务1合成评测资料']).fetchone()
    assert knowledge and knowledge['meta'].get('evaluation_corpus_hash') == dataset_digest(corpus)
    identity = knowledge['id']
    assert Model.objects.filter(id=knowledge['embedding_model_id']).exists()
    with psycopg.connect(**connection.get_connection_params()) as target:
        for table in ('knowledge', 'document', 'paragraph', 'embedding'):
            field = 'id' if table == 'knowledge' else 'knowledge_id'
            query = sql.SQL('COPY (SELECT * FROM {} WHERE {}={}) TO STDOUT').format(
                sql.Identifier(table), sql.Identifier(field), sql.Literal(identity))
            with source.cursor().copy(query) as outgoing, target.cursor().copy(
                    sql.SQL('COPY {} FROM STDIN').format(sql.Identifier(table))) as incoming:
                for block in outgoing:
                    incoming.write(block)

flow = json.loads((root / 'apps/application/flow/default_workflow.json').read_text())
base, start = flow['nodes'][:2]
base['properties'].update(user_input_field_list=[], api_input_field_list=[])
base['properties']['node_data'].update(name='任务6模型路由验收', prologue='任务6本地验收；所有调用计入100元累计上限。')
search = next(n for n in flow['nodes'] if n['type'] == 'search-dataset-node')
search['id'] = 'task6-search'
search['type'] = 'search-knowledge-node'
search['properties']['stepName'] = '知识库检索'
search['properties']['node_data'] = {'knowledge_id_list': [str(identity)], 'knowledge_setting': {
    'top_n': 5, 'similarity': 0.2, 'search_mode': 'embedding', 'max_paragraph_char_number': 5000},
    'question_reference_address': ['start-node', 'question'], 'show_knowledge': True, 'search_scope_type': 'custom',
    'search_scope_source': 'knowledge', 'search_scope_reference': []}
ai = next(n for n in flow['nodes'] if n['type'] == 'ai-chat-node')
ai['id'] = 'task6-ai'
ai['properties']['node_data'] = {'model_id': low, 'model_id_type': 'custom',
    'system': '仅根据资料和对话回答；缺少依据明确说明。答案简洁。answer内保留资料方括号证据ID引用。',
    'prompt': '问题：{{开始.question}}', 'dialogue_number': 3, 'dialogue_type': 'WORKFLOW', 'is_result': True,
    'model_params_setting': {'temperature': 0, 'max_tokens': 512, 'extra_body': {'enable_thinking': False}},
    'model_routing': {'enabled': True, 'low': {'model_id': low, 'params': {'temperature': 0, 'max_tokens': 512, 'enable_thinking': False}},
        'high': {'model_id': high, 'params': {'temperature': 0, 'max_tokens': 512, 'enable_thinking': False}},
        'timeout': 60, 'contract': {'required_fields': ['answer'], 'citation_field': 'refs',
                                  'evidence_reference': ['task6-search', 'paragraph_list']}}}
nodes = [base, start, search, ai]
edges = [{'id': 'task6-'+str(i), 'type': 'app-edge', 'sourceNodeId': a, 'targetNodeId': b,
          'sourceAnchorId': a+'_right', 'targetAnchorId': b+'_left', 'startPoint': {'x':1,'y':1},
          'endPoint': {'x':2,'y':1}, 'properties': {}} for i,(a,b) in enumerate([('start-node','task6-search'),('task6-search','task6-ai')])]
app = Application.objects.create(name='任务6模型路由验收', workspace_id='default', user=owner,
                                type='WORK_FLOW', model_id=low, work_flow={'nodes':nodes,'edges':edges}, dialogue_number=3)
ApplicationOperateSerializer(data={'application_id':str(app.id),'workspace_id':'default','user_id':str(owner.id)}).publish({})
access = ApplicationAccessToken.objects.get(application=app)
access.access_num=10000
access.show_exec=True
access.save()
fixture={'application_id':str(app.id),'user_id':str(owner.id),'knowledge_id':str(identity),'low_model_id':low,'high_model_id':high}
(root/'task6-fixture.json').write_text(json.dumps(fixture,indent=2))
(root/'task6-private-access.json').write_text(json.dumps({'access_token':access.access_token}))
os.chmod(root/'task6-private-access.json',0o600)
print(json.dumps({**fixture,'default_staging_login_valid':password_verify(CONFIG.get('DEFAULT_PASSWORD','MaxKB@123..'),owner.password)}))
connection.close();sys.stdout.flush();os._exit(0)
