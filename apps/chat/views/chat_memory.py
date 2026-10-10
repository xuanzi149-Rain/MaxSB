from common.auth import TokenAuth
from common.auth.authentication import has_permissions
from common.constants.permission_constants import PermissionConstants, RoleConstants, ViewPermission, CompareConstants
# coding=utf-8
from dataclasses import asdict
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from common.auth import ChatTokenAuth
from common.result import result
from application.conversation_memory.store import MemoryStore, MemoryConflict, MemoryDenied
from application.conversation_memory.types import Identity, Operation
from chat.serializers.chat_memory import MemoryMutationSerializer


class ChatMemoryView(APIView):
    authentication_classes = [ChatTokenAuth]

    def access(self, request, chat_id, **kwargs):
        auth = request.auth
        if auth is None:
            raise MemoryDenied('Authentication required')
        return MemoryStore(), Identity(str(auth.application_id), str(auth.chat_user_id), str(auth.chat_user_type)), False

    def operate(self, request, chat_id, fact_id=None, **kwargs):
        try:
            store, identity, temporary = self.access(request, chat_id, **kwargs)
            state = store.read(identity, chat_id)  # Authorize before parsing mutations.
            if request.method != 'GET':
                serializer = MemoryMutationSerializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                value = serializer.validated_data
                if request.method == 'DELETE':
                    state = store.clear(identity, chat_id, value['expected_version'], str(value['request_id']))
                else:
                    if not fact_id or 'operation' not in value:
                        raise ValidationError('Fact and operation required')
                    state = store.correct(identity, chat_id, str(fact_id),
                                          Operation(value['operation'], value=value.get('value', '')),
                                          value['expected_version'], str(value['request_id']))
            return result.success({**asdict(state), 'sources': store.sources(identity, chat_id), 'temporary': temporary})
        except MemoryDenied:
            return result.Result(code=404, message='Conversation unavailable', response_status=404)
        except MemoryConflict as exc:
            return result.Result(code=409, message=str(exc), response_status=409)

    def get(self, request, chat_id, **kwargs):
        return self.operate(request, chat_id, **kwargs)

    def patch(self, request, chat_id, fact_id, **kwargs):
        return self.operate(request, chat_id, fact_id, **kwargs)

    def delete(self, request, chat_id, **kwargs):
        return self.operate(request, chat_id, **kwargs)




class DebugMemoryView(ChatMemoryView):
    authentication_classes = [TokenAuth]

    def access(self, request, chat_id, workspace_id, application_id, **kwargs):
        from application.serializers.common import ChatInfo
        from application.conversation_memory.temporary import TemporaryMemoryStore
        info = ChatInfo.get_cache(str(chat_id))
        if (not info or not info.debug or str(info.application_id) != str(application_id)
                or str(info.chat_user_id) != str(request.user.id)
                or str(info.application.workspace_id) != str(workspace_id)):
            raise MemoryDenied('Conversation unavailable')
        identity = Identity(str(application_id), str(request.user.id), str(info.chat_user_type))
        return TemporaryMemoryStore(identity, chat_id), identity, True

    @has_permissions(PermissionConstants.APPLICATION_EDIT.get_workspace_application_permission(),
                     PermissionConstants.APPLICATION_EDIT.get_workspace_permission_workspace_manage_role(),
                     ViewPermission([RoleConstants.USER.get_workspace_role()],
                                    [PermissionConstants.APPLICATION.get_workspace_application_permission()],
                                    CompareConstants.AND),
                     RoleConstants.WORKSPACE_MANAGE.get_workspace_role())
    def operate(self, request, chat_id, fact_id=None, **kwargs):
        return super().operate(request, chat_id, fact_id, **kwargs)
