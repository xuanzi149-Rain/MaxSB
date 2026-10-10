# coding=utf-8
from types import SimpleNamespace as NS
from uuid import uuid4
import json
from rest_framework.test import APIRequestFactory, force_authenticate
from application.tests_tool_recovery_store import RecoveryFixture
from chat.views.tool_recovery import ToolRunView


class ApiTests(RecoveryFixture):
    def request(self, user='owner', method='get', body=None):
        factory = APIRequestFactory()
        request = getattr(factory, method)('/tool_runs/' + str(self.run.id), body or {}, format='json')
        force_authenticate(request, user=NS(id='actor'), token=NS(application_id=self.app.id,
                           chat_user_id=user, chat_user_type='CHAT_USER'))
        return ToolRunView.as_view()(request, run_id=self.run.id)

    def test_other_user_cannot_read_or_resume(self):
        self.assertEqual(self.request('other').status_code, 404)
        self.assertEqual(self.request('other', 'post', {}).status_code, 404)

    def test_snapshot_and_keys_not_exposed(self):
        self.fail_tool()
        response = self.request()
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)['data']
        self.assertNotIn('details', data)
        self.assertNotIn('snapshot', data)
        self.assertNotIn('inputs', data['steps'][0])
        self.assertNotIn('key', data['steps'][0])
        self.assertEqual(data['steps'][0]['attempts'][0]['error_type'], 'timeout')

    def test_resume_cannot_override_inputs(self):
        self.fail_tool()
        response = self.request(method='post', body={'request_id': str(uuid4()), 'expected_version': 2,
                                                   'inputs': {'unsafe': True}})
        self.assertEqual(response.status_code, 400)
