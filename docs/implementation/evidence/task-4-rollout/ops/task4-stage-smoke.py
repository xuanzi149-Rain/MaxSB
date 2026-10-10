import atexit
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
from uuid import uuid4

BASE = 'http://127.0.0.1:8084'
fixture = json.loads(Path('/private/tmp/task4-stage-fixture.json').read_text())
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
phase = sys.argv[1]
records = []

def save_result():
    value = globals().get('result', {'phase': phase, 'passed': False, 'records': records})
    Path('/private/tmp/task4-stage-' + phase + '.json').write_text(json.dumps(value, ensure_ascii=False, indent=2))

atexit.register(save_result)


def call(path, method='GET', data=None, token=None):
    start = time.monotonic()
    req = urllib.request.Request(BASE + '/chat/api' + path,
        data=json.dumps(data).encode() if data is not None else None, method=method,
        headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + token} if token else {})})
    with opener.open(req, timeout=120) as response:
        value = json.loads(response.read())
    assert value['code'] == 200, value
    if path.startswith('/chat_message/'):
        records.append({'question': data['message'], 'seconds': round(time.monotonic()-start, 3), 'response': value})
    return value['data']


def send(chat, token, message):
    return call('/chat_message/' + chat, 'POST', {'message': message, 'stream': False, 're_chat': False}, token)


private_state = Path('/private/tmp/task4-stage-session.json')
if phase == 'restart':
    state = json.loads(private_state.read_text())
    token, chat = state['token'], state['chat']
    memory = call('/chat_memory/' + chat, token=token)
    assert any('4600' in f['value'] for f in memory['facts']), memory
    answer = send(chat, token, '我的咖啡机预算是多少？')
    assert '4600' in answer['content'], answer
    memory = call('/chat_memory/' + chat, token=token)
    cleared = call('/chat_memory/' + chat, 'DELETE', {'expected_version': memory['version'], 'request_id': str(uuid4())}, token)
    assert cleared['facts'] == [], cleared
    answer = send(chat, token, '清除之后，你知道我已确定的咖啡机预算吗？')
    assert '4600' not in answer['content'] and '1900' not in answer['content'], answer
    assert any(word in answer['content'] for word in ['未知', '不知道', '不清楚', '无法', '没有', '不确定', '未']), answer
    memory = call('/chat_memory/' + chat, token=token)
    assert memory['facts'] == [], memory
else:
    token = call('/auth/anonymous', 'POST', {'access_token': fixture['public_access_token']})
    chat = call('/open', token=token)
    answer = send(chat, token, '我的咖啡机预算是1900元，请记住。')
    memory = call('/chat_memory/' + chat, token=token)
    if phase in {'disabled', 'rollback'}:
        assert memory['facts'] == [], memory
    elif phase == 'enabled':
        fact = next(f for f in memory['facts'] if '1900' in f['value'])
        memory = call('/chat_memory/' + chat + '/facts/' + fact['id'], 'PATCH',
                      {'operation': 'replace', 'value': '4600元', 'expected_version': memory['version'],
                       'request_id': str(uuid4())}, token)
        answer = send(chat, token, '我的咖啡机预算是多少？')
        assert '4600' in answer['content'], answer
        private_state.write_text(json.dumps({'token': token, 'chat': chat}))
        os.chmod(private_state, 0o600)
    else:
        raise ValueError(phase)
result = {'phase': phase, 'passed': True, 'chat_id': chat, 'records': records, 'memory': memory}
Path('/private/tmp/task4-stage-' + phase + '.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({'phase': phase, 'passed': True, 'answers': [r['response']['data']['content'] for r in records],
                  'seconds': [r['seconds'] for r in records]}, ensure_ascii=False))
