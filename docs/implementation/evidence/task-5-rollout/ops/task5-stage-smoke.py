"""Real HTTP deployment probe; no model or external tool calls."""
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

BASE = 'http://127.0.0.1:8084'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
fixture = json.loads(Path('/private/tmp/task5-private-fixture.json').read_text())
state_path = Path('/private/tmp/task5-probe-session.json')
phase = sys.argv[1]

def call(path, data=None, token=None):
    req = urllib.request.Request(BASE + '/chat/api' + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer '+token} if token else {})})
    with opener.open(req, timeout=90) as response:
        result = json.loads(response.read())
    assert result['code'] == 200, result
    return result['data']

if phase == 'enabled':
    token = call('/auth/anonymous', {'access_token': fixture['access_token']})
    chat = call('/open', token=token)
    call('/chat_message/' + chat, {'message':'部署验证，不调用模型。', 'stream':False, 're_chat':False}, token)
    runs = call('/chat/' + chat + '/tool_runs', token=token)
    assert len(runs) == 1 and runs[0]['status'] == 'succeeded', runs
    assert len(runs[0]['steps']) == 2 and runs[0]['steps'][0]['status'] == 'succeeded', runs
    assert 'details' not in runs[0]
    state_path.write_text(json.dumps({'token':token,'chat':chat,'run':runs[0]['id']}))
    os.chmod(state_path,0o600)
    result={'phase':phase,'run_status':runs[0]['status'],'persisted_steps':len(runs[0]['steps']), 'passed':True}
elif phase == 'restart':
    state=json.loads(state_path.read_text())
    run=call('/tool_runs/'+state['run'],token=state['token'])
    assert run['status']=='succeeded'
    result={'phase':phase,'run_status':run['status'],'passed':True}
elif phase == 'disabled':
    token=call('/auth/anonymous',{'access_token':fixture['access_token']})
    chat=call('/open',token=token)
    call('/chat_message/'+chat,{'message':'关闭恢复后的兼容验证。','stream':False,'re_chat':False},token)
    assert call('/chat/'+chat+'/tool_runs',token=token)==[]
    result={'phase':phase,'recovery_runs':0,'passed':True}
else:
    raise ValueError('Unknown phase')
assets=[]
for spa in ['admin','chat']:
    with opener.open(BASE+'/'+spa+'/',timeout=10) as response:
        html=response.read().decode()
        assert response.status==200
    script=re.search(r'<script[^>]+src="([^"]+\.js)"',html).group(1)
    url=urllib.parse.urljoin(BASE+'/'+spa+'/',script)
    with opener.open(url,timeout=10) as response:
        assert response.status==200 and len(response.read())>100
    assets.append({'spa':spa,'html':200,'entry_js':200})
result['static']=assets
Path('/private/tmp/task5-stage-'+phase+'.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
