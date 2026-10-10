# coding=utf-8
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from common.auth import ChatTokenAuth, TokenAuth
from common.result import result
from common.auth.authentication import has_permissions
from common.constants.permission_constants import PermissionConstants, RoleConstants
from application.models import Application, ChatRecord, ToolRun
from application.tool_recovery.types import Identity, RecoveryConflict, RecoveryDenied
from application.tool_recovery.store import RecoveryStore, checkpoint_payload
from application.tool_recovery.runtime import current_version, definition_fingerprint
from chat.serializers.tool_recovery import ResumeSerializer, ResolutionSerializer


def public_run(run, include_details=False):
    steps = []
    for step in run.steps.order_by('id'):
        steps.append({'node_id': step.node_id, 'status': step.status, 'error_type': step.error_type,
                      'attempts': list(step.attempts.order_by('id').values('id', 'generation', 'status', 'error_type',
                                      'started_at', 'ended_at', 'wait_seconds'))})
    payload = checkpoint_payload(run)
    if not include_details:
        payload.pop('details', None)
    return {**payload, 'id': str(run.id), 'status': run.status, 'version': run.version, 'resumes': run.resumes,
            'record_id': str(run.record_id), 'steps': steps, 'failed_node': run.failed_node,
            'can_resume': run.status == 'failed' and run.resumes < 3 and any(
                s['node_id'] == run.failed_node and s['error_type'] in {'timeout', 'transient', 'checkpoint', 'confirmed', 'not_started'} for s in steps)}


def validate_resume(run):
    version = current_version(run.chat.application_id)
    if definition_fingerprint(version) != run.snapshot['fingerprint']:
        raise RecoveryConflict('Workflow or tool changed; start a new run')
    if ChatRecord.objects.filter(chat=run.chat, create_time__gt=run.created_at).exclude(id=run.record_id).exists():
        raise RecoveryConflict('Conversation advanced; this run cannot resume')
    return version


def resume_run(identity, run, request_id, expected_version):
    from application.serializers.common import ChatInfo
    from application.flow.common import Workflow
    from application.flow.i_step_node import WorkFlowPostHandler
    from application.flow.workflow_manage import WorkflowManage
    from application.tool_recovery.runtime import RecoveryRuntime
    version = validate_resume(run)
    # Current reference tool permissions are checked before claiming or making a request.
    from common.utils.shared_resource_auth import get_runtime_user_id, validate_authorized_tool_ids
    refs = [n['properties']['node_data']['mcp_tool_id'] for n in version.work_flow['nodes']
            if n['type'] == 'mcp-node' and n['properties'].get('node_data', {}).get('mcp_source') == 'referencing']
    validate_authorized_tool_ids(refs, run.snapshot['params']['workspace_id'],
                                get_runtime_user_id(chat_user_id=identity.chat_user_id,
                                                    chat_user_type=identity.chat_user_type))
    claim = RecoveryStore().claim(identity, run.id, request_id, expected_version)
    if not claim.acquired:
        return
    params = {**run.snapshot['params'], 'stream': False, 're_chat': False, 'debug': False,
              'history_chat_record': [ChatRecord(**r) for r in run.snapshot['history']]}
    info = ChatInfo(str(run.chat_id), identity.chat_user_id, identity.chat_user_type,
                    params.get('ip_address', ''), params.get('source') or {}, [], [], identity.application_id)
    info.application = version
    info.chat_record_list = list(params['history_chat_record'])
    manager = WorkflowManage(Workflow.new_instance(version.work_flow), params, WorkFlowPostHandler(info),
                             form_data=run.snapshot['form_data'])
    manager.chat_record = ChatRecord.objects.filter(id=run.record_id, chat_id=run.chat_id).first()
    manager.recovery = RecoveryRuntime(manager, claim)
    manager.run()


class ToolRunView(APIView):
    authentication_classes = [ChatTokenAuth]

    def access(self, request, run_id):
        if request.auth is None:
            raise RecoveryDenied('Run unavailable')
        auth = request.auth
        identity = Identity(str(auth.application_id), str(auth.chat_user_id), str(auth.chat_user_type))
        return identity, RecoveryStore().read(identity, run_id)

    def get(self, request, run_id):
        try:
            _, run = self.access(request, run_id)
            RecoveryStore().reconcile_expired(run_id)
            run.refresh_from_db()
            return result.success(public_run(run))
        except RecoveryDenied:
            return result.Result(code=404, message='Run unavailable', response_status=404)

    def post(self, request, run_id):
        try:
            identity, run = self.access(request, run_id)
            value = ResumeSerializer(data=request.data)
            value.is_valid(raise_exception=True)
            resume_run(identity, run, str(value.validated_data['request_id']), value.validated_data['expected_version'])
            run.refresh_from_db()
            data = public_run(run)
            return result.success(data)
        except RecoveryDenied:
            return result.Result(code=404, message='Run unavailable', response_status=404)
        except RecoveryConflict as exc:
            return result.Result(code=409, message=str(exc), response_status=409)
        except (ValueError, ValidationError) as exc:
            return result.Result(code=400, message=str(exc), response_status=400)


class ManageToolRunView(APIView):
    authentication_classes = [TokenAuth]

    def access(self, run_id, workspace_id, application_id):
        if not Application.objects.filter(id=application_id, workspace_id=workspace_id).exists():
            raise RecoveryDenied('Run unavailable')
        run = ToolRun.objects.filter(id=run_id, chat__application_id=application_id, chat__is_deleted=False).first()
        if run is None:
            raise RecoveryDenied('Run unavailable')
        return run

    @has_permissions(PermissionConstants.APPLICATION_EDIT.get_workspace_application_permission(),
                     PermissionConstants.APPLICATION_EDIT.get_workspace_permission_workspace_manage_role(),
                     RoleConstants.WORKSPACE_MANAGE.get_workspace_role())
    def get(self, request, workspace_id, application_id, run_id):
        try:
            run = self.access(run_id, workspace_id, application_id)
            data = public_run(run, include_details=True)
            data['resolution'] = run.resolution
            return result.success(data)
        except RecoveryDenied:
            return result.Result(code=404, message='Run unavailable', response_status=404)

    @has_permissions(PermissionConstants.APPLICATION_EDIT.get_workspace_application_permission(),
                     PermissionConstants.APPLICATION_EDIT.get_workspace_permission_workspace_manage_role(),
                     RoleConstants.WORKSPACE_MANAGE.get_workspace_role())
    def post(self, request, workspace_id, application_id, run_id):
        try:
            run = self.access(run_id, workspace_id, application_id)
            value = ResolutionSerializer(data=request.data)
            value.is_valid(raise_exception=True)
            data = value.validated_data
            run = RecoveryStore().resolve(run.id, request.user.id, str(data['request_id']), data['expected_version'],
                                          data['conclusion'], data['evidence'], data.get('output'))
            return result.success(public_run(run))
        except RecoveryDenied:
            return result.Result(code=404, message='Run unavailable', response_status=404)
        except RecoveryConflict as exc:
            return result.Result(code=409, message=str(exc), response_status=409)
        except (ValueError, ValidationError) as exc:
            return result.Result(code=400, message=str(exc), response_status=400)


class ChatToolRunsView(APIView):
    authentication_classes = [ChatTokenAuth]

    def get(self, request, chat_id):
        try:
            auth = request.auth
            if auth is None:
                raise RecoveryDenied('Run unavailable')
            identity = Identity(str(auth.application_id), str(auth.chat_user_id), str(auth.chat_user_type))
            RecoveryStore()._chat(identity, chat_id)
            runs = list(ToolRun.objects.filter(chat_id=chat_id).order_by('-created_at')[:10])
            for run in runs:
                RecoveryStore().reconcile_expired(run.id)
                run.refresh_from_db()
            return result.success([public_run(r) for r in runs])
        except RecoveryDenied:
            return result.Result(code=404, message='Run unavailable', response_status=404)
