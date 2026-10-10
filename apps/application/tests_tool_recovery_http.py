# coding=utf-8
from uuid import uuid4
import requests
from django.test import LiveServerTestCase, override_settings
from application.tests_tool_recovery_store import RecoveryFixture
from application.models import ApplicationAccessToken
from common.auth.common import ChatUserToken, ChatAuthentication
from common.constants.authentication_type import AuthenticationType


@override_settings(ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'])
class HttpTests(LiveServerTestCase):
    setUp = RecoveryFixture.setUp

    def token(self, user):
        return ChatUserToken(self.app.id, None, self.access, AuthenticationType.CHAT_ANONYMOUS_USER,
                             'ANONYMOUS_USER', user, ChatAuthentication(None)).to_token()

    def test_real_http_authentication_and_isolation(self):
        self.access = str(uuid4())
        self.chat.chat_user_type = 'ANONYMOUS_USER'
        self.chat.save()
        ApplicationAccessToken.objects.create(application=self.app, access_token=self.access)
        url = self.live_server_url + '/chat/api/tool_runs/' + str(self.run.id)
        headers = {'Authorization': 'Bearer ' + self.token('owner')}
        response = requests.get(url, headers=headers, timeout=10)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['id'], str(self.run.id))
        response = requests.get(url, headers={'Authorization': 'Bearer ' + self.token('other')}, timeout=10)
        self.assertEqual(response.status_code, 404)
        response = requests.post(url + '/resume', headers=headers, json={'inputs': {}}, timeout=10)
        self.assertEqual(response.status_code, 400)
        response = requests.get(url, timeout=10)
        self.assertNotEqual(response.json().get('code'), 200)

    def test_http_resume_replay_persists_one_record(self):
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        from application.models import ApplicationVersion, ToolRun, ChatRecord
        from application.tests_tool_recovery_runtime import graph
        from application.flow.common import Workflow
        from application.flow.workflow_manage import WorkflowManage
        from application.flow.i_step_node import WorkFlowPostHandler
        from application.serializers.common import ChatInfo
        from application.tool_recovery.runtime import RecoveryRuntime
        owner = str(uuid4())
        self.chat.chat_user_id = owner
        self.access = str(uuid4())
        self.chat.chat_user_type = 'ANONYMOUS_USER'
        self.chat.save()
        ApplicationAccessToken.objects.create(application=self.app, access_token=self.access, show_exec=False)
        definition = graph()
        version = ApplicationVersion.objects.create(application=self.app, name='http', work_flow=definition)
        params = {'chat_id': str(self.chat.id), 'chat_record_id': str(uuid4()), 'question': 'test',
                  'application_id': str(self.app.id), 'workspace_id': 'default', 'chat_user_id': owner,
                  'chat_user_type': 'ANONYMOUS_USER', 'stream': False, 'history_chat_record': [],
                  're_chat': False, 'debug': False}
        info = ChatInfo(str(self.chat.id), owner, 'ANONYMOUS_USER', '', {}, [], [], str(self.app.id))
        info.application = version
        manager = WorkflowManage(Workflow.new_instance(definition), params, WorkFlowPostHandler(info))
        manager.recovery = RecoveryRuntime(manager)
        calls = []
        async def call(*args):
            calls.append(1)
            if len(calls) == 2:
                raise TimeoutError()
            return NS(isError=False, content=[NS(text='receipt')])
        with patch('application.flow.backend.sandbox_mcp.SandboxMCPBackend.call_tool', call), \
                patch('application.flow.i_step_node.extract_long_term_memory.apply_async'):
            manager.run_chain_manage(None, None)
            run = ToolRun.objects.get(record_id=params['chat_record_id'])
            url = self.live_server_url + '/chat/api/tool_runs/' + str(run.id) + '/resume'
            headers = {'Authorization': 'Bearer ' + self.token(owner)}
            body = {'request_id': str(uuid4()), 'expected_version': run.version}
            response = requests.post(url, headers=headers, json=body, timeout=20)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['data']['status'], 'succeeded', response.text)
            self.assertNotIn('details', response.json()['data'])
            self.assertEqual(calls, [1, 1, 1])
            response = requests.post(url, headers=headers, json=body, timeout=20)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(calls, [1, 1, 1])
            self.assertEqual(ChatRecord.objects.filter(id=run.record_id).count(), 1)
        manager.recovery.close()
