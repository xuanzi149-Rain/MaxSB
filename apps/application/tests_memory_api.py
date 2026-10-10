# coding=utf-8
import json
from types import SimpleNamespace
from uuid import uuid4
from rest_framework.test import APIRequestFactory, force_authenticate
from application.tests_memory_store import MemoryFixture
from chat.views.chat_memory import ChatMemoryView


class MemoryAPITests(MemoryFixture):
    def request(self, method='get', identity=None, data=None):
        request = getattr(APIRequestFactory(), method)('/chat_memory/' + str(self.chat.id), data=data, format='json')
        auth = identity or self.identity
        force_authenticate(request, user=SimpleNamespace(is_authenticated=True), token=auth)
        return ChatMemoryView.as_view()(request, chat_id=str(self.chat.id))

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
