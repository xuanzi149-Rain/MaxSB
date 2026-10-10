# coding=utf-8
import json
from types import SimpleNamespace
from uuid import uuid4
from rest_framework.test import APIRequestFactory, force_authenticate
from application.tests_memory_store import MemoryFixture
from chat.views.chat_memory import ChatMemoryView


class MemoryAPITests(MemoryFixture):
    def request(self, method='get', identity=None, data=None, fact_id=None):
        request = getattr(APIRequestFactory(), method)('/chat_memory/' + str(self.chat.id), data=data, format='json')
        auth = identity or self.identity
        force_authenticate(request, user=SimpleNamespace(is_authenticated=True), token=auth)
        kwargs = {'fact_id': fact_id} if fact_id else {}
        return ChatMemoryView.as_view()(request, chat_id=str(self.chat.id), **kwargs)

    def test_get_hides_other_user(self):
        from application.conversation_memory.types import Identity
        self.assertEqual(self.request(identity=Identity(str(self.app.id), 'other', 'CHAT_USER')).status_code, 404)

    def test_clear_returns_version_and_keeps_chat(self):
        response = self.request('delete', data={'expected_version': 0, 'request_id': str(uuid4())})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['data']['generation'], 1)
        self.assertEqual(self.request('delete', data={'expected_version': 0, 'request_id': str(uuid4())}).status_code, 409)

    def test_body_cannot_override_identity(self):
        from application.conversation_memory.types import Identity
        response = self.request('delete', Identity(str(self.app.id), 'other', 'CHAT_USER'),
                     {'chat_user_id': 'owner', 'expected_version': 0, 'request_id': str(uuid4())})
        self.assertEqual(response.status_code, 404)

    def test_real_authentication_rejects_missing_token(self):
        request = APIRequestFactory().get('/chat_memory/' + str(self.chat.id))
        response = ChatMemoryView.as_view()(request, chat_id=str(self.chat.id))
        self.assertEqual(response.status_code, 401)

    def test_correction_sources_and_stale_version(self):
        from application.conversation_memory.policy import apply_operations
        from application.conversation_memory.types import Operation
        ticket = self.begin()
        state = self.store.commit_turn(ticket, apply_operations(ticket.snapshot, [Operation(
            'add', entity='旅行', attribute='预算', value='3000', source=ticket.event_id, quote='预算3000')]))
        data = {'operation': 'replace', 'value': '4000', 'expected_version': state.version, 'request_id': str(uuid4())}
        response = self.request('patch', data=data, fact_id=state.facts[0]['id'])
        self.assertEqual(response.status_code, 200)
        payload = json.loads(self.request().content)['data']
        self.assertEqual(payload['facts'][0]['value'], '4000')
        self.assertTrue(any(s['kind'] == 'manual' for s in payload['sources']))
        data['request_id'] = str(uuid4())
        self.assertEqual(self.request('patch', data=data, fact_id=state.facts[0]['id']).status_code, 409)

    def test_other_application_client_type_and_deleted_chat_denied(self):
        from application.conversation_memory.types import Identity
        for identity in [Identity(str(uuid4()), 'owner', 'CHAT_USER'),
                         Identity(str(self.app.id), 'owner', 'ANONYMOUS_USER')]:
            self.assertEqual(self.request(identity=identity).status_code, 404)
        self.chat.is_deleted = True
        self.chat.save()
        self.assertEqual(self.request().status_code, 404)
