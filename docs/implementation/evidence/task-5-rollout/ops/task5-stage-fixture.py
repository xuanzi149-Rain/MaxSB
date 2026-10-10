"""Create/toggle a no-model deployment probe in the isolated staging database."""
import json
import os
from pathlib import Path
import runpy
import sys

scope = runpy.run_path('/tmp/task5-stage-control.py', run_name='stage_operations')
from application.models import Application, ApplicationAccessToken, ToolRun
from application.serializers.application import ApplicationOperateSerializer
from users.models import User
root = scope['ROOT']
path = root / 'task5-private-fixture.json'
command = sys.argv[1]
if command == 'create':
    assert not path.exists()
    source = json.loads((root / 'apps/application/flow/default_workflow.json').read_text())
    nodes = [n for n in source['nodes'] if n['type'] in {'base-node', 'start-node'}]
    for node in nodes:
        if node['type'] == 'base-node':
            node['properties'].update(user_input_field_list=[], api_input_field_list=[])
            node['properties']['node_data'].update(name='任务5部署验证', prologue='仅检查恢复运行和数据库，不调用模型。')
        else:
            node['properties'].setdefault('node_data', {})['tool_recovery'] = True
    owner = User.objects.first()
    from models_provider.models import Model
    from common.utils.rsa_util import rsa_long_encrypt
    model = Model.objects.filter(name='任务5本地协议验证',workspace_id='default').first()
    if model is None:
        model = Model.objects.create(name='任务5本地协议验证', model_type='LLM', model_name='gpt-4o-mini',
        provider='model_openai_provider', user=owner, workspace_id='default',
        credential=rsa_long_encrypt(json.dumps({'api_base':'http://127.0.0.1:18085/v1','api_key':'local-fixture-only'})))
    ai = next(n for n in source['nodes'] if n['type']=='ai-chat-node')
    ai['id']='probe-ai'
    ai['properties']['node_data']={'model_id':str(model.id),'system':'Local protocol test', 'prompt':'hello',
        'dialogue_number':0, 'is_result':True, 'model_params_setting':{'temperature':0,'max_tokens':64}}
    nodes.append(ai)
    flow={'nodes':nodes,'edges':[{'id':'start-probe','type':'app-edge','sourceNodeId':'start-node',
        'targetNodeId':'probe-ai','sourceAnchorId':'start-node_right','targetAnchorId':'probe-ai_left',
        'startPoint':{'x':1,'y':1},'endPoint':{'x':2,'y':1},'properties':{}}]}
    app = Application.objects.filter(name='任务5部署验证', workspace_id='default').first()
    if app is None:
        app=Application(name='任务5部署验证', type='WORK_FLOW', user=owner, workspace_id='default')
    app.work_flow, app.model=flow,model
    app.save()
elif command == 'disable':
    fixture = json.loads(path.read_text())
    app = Application.objects.get(id=fixture['application_id'])
    assert app.name == '任务5部署验证'
    next(n for n in app.work_flow['nodes'] if n['type'] == 'start-node')['properties']['node_data']['tool_recovery'] = False
    app.save(update_fields=['work_flow'])
else:
    raise ValueError('Unknown command')
ApplicationOperateSerializer(data={'application_id': str(app.id), 'workspace_id': app.workspace_id,
                                  'user_id': str(app.user_id)}).publish({})
if command == 'create':
    access = ApplicationAccessToken.objects.get(application=app)
    path.write_text(json.dumps({'application_id': str(app.id), 'access_token': access.access_token}))
    os.chmod(path, 0o600)
print(json.dumps({'application_id': str(app.id), 'operation': command, 'database': scope['DB'],
                  'runs': ToolRun.objects.filter(chat__application=app).count()}))
scope['connection'].close()
sys.stdout.flush()
os._exit(0)
