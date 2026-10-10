# coding=utf-8
"""Fenced checkpoints at the existing serial scheduler's node boundary."""
import hashlib
import json
import threading
from django.db import close_old_connections
from application.models import ApplicationVersion
from common.encoder.encoder import SystemEncoder
from .config import validate_recovery_workflow
from .store import RecoveryStore
from .types import Identity, RecoveryConflict


def encode(value):
    return json.loads(json.dumps(value, cls=SystemEncoder, allow_nan=False))


def definition_fingerprint(version):
    from tools.models import Tool
    tools = {}
    for node in version.work_flow.get('nodes', []):
        data = node.get('properties', {}).get('node_data') or {}
        tool_id = data.get('mcp_tool_id')
        if node['type'] == 'mcp-node' and data.get('mcp_source') == 'referencing' and tool_id:
            tool = Tool.objects.filter(id=tool_id, is_active=True).first()
            if not tool:
                raise RecoveryConflict('Referenced tool unavailable')
            tools[str(tool_id)] = {'code': tool.code, 'init_params': getattr(tool, 'init_params', {})}
    value = encode({'version': str(version.id), 'workflow': version.work_flow, 'tools': tools})
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def current_version(application_id):
    version = ApplicationVersion.objects.filter(application_id=application_id).order_by('-create_time').first()
    if version is None:
        raise RecoveryConflict('Published application unavailable')
    return version


class RecoveryRuntime:
    def __init__(self, manager, claim=None):
        self.manager, self.store = manager, RecoveryStore()
        if not validate_recovery_workflow(manager.flow):
            raise ValueError('Recovery is disabled')
        p = manager.params
        if p.get('debug') or p.get('re_chat') or manager.start_node_id or any(
                getattr(manager, k) for k in ('image_list', 'document_list', 'audio_list', 'video_list', 'other_list')):
            raise ValueError('Recovery requires a new formal text workflow run')
        self.identity = Identity(str(p['application_id']), str(p['chat_user_id']), str(p['chat_user_type']))
        version = current_version(p['application_id'])
        supplied = manager.work_flow_post_handler.chat_info.application
        if str(supplied.id) != str(version.id) or supplied.work_flow != version.work_flow:
            raise RecoveryConflict('Workflow version changed before execution')
        fingerprint = definition_fingerprint(version)
        self._stop = threading.Event()
        self._heartbeat_error = None
        if claim:
            self.run = self.store.read(self.identity, claim.run_id)
            if self.run.snapshot['fingerprint'] != fingerprint:
                raise RecoveryConflict('Workflow or tool version changed; start a new run')
            self.claim = claim
        else:
            history = [{k: encode(getattr(r, k)) for k in ('id', 'problem_text', 'answer_text', 'details')}
                       for r in p.get('history_chat_record', [])]
            nodes = {n.id: n for n in manager.flow.nodes}
            following = {e.sourceNodeId: e.targetNodeId for e in manager.flow.edges}
            ordered, current = [], next(n.id for n in nodes.values() if n.type == 'start-node')
            while current is not None:
                ordered.append({'id': current, 'type': nodes[current].type})
                current = following.get(current)
            snapshot = {'node_order': ordered, 'fingerprint': fingerprint, 'node_ids': [n.id for n in manager.flow.nodes if n.type != 'base-node'], 'params': encode({k: p.get(k) for k in (
                'chat_id', 'chat_record_id', 'question', 'application_id', 'workspace_id', 'chat_user_id',
                'chat_user_type', 'chat_user', 'chat_user_group', 'ip_address', 'source')}),
                'history': history, 'form_data': encode(manager.form_data)}
            self.run = self.store.create(self.identity, p['chat_id'], p['chat_record_id'], snapshot)
            self.claim = self.store.initial_claim(self.run)
        self.thread = None

    def start_heartbeat(self):
        if self.thread:
            return
        def beat():
            close_old_connections()
            try:
                while not self._stop.wait(15):
                    try:
                        self.store.heartbeat(self.claim)
                    except Exception as exc:
                        self._heartbeat_error = exc
                        return
            finally:
                close_old_connections()
        self.thread = threading.Thread(target=beat, daemon=True)
        self.thread.start()

    def before_node(self, node):
        if self._heartbeat_error:
            raise RecoveryConflict('Recovery heartbeat failed')
        if definition_fingerprint(current_version(self.identity.application_id)) != self.run.snapshot['fingerprint']:
            raise RecoveryConflict('Workflow or tool changed during execution')
        self.store.heartbeat(self.claim)
        step = self.store.begin_step(self.claim, node.id, node.type)
        if step.status != 'succeeded':
            return False
        node.context = step.output['context']
        node.answer_text = step.output.get('answer_text')
        node.status = 200
        self.manager.context = step.variables['context']
        self.manager.chat_context = step.variables['chat_context']
        node.node_chunk.end()
        return True

    def after_node(self, node):
        # The actual prompt message objects are not reference outputs or checkpoints.
        context = {k: v for k, v in node.context.items() if k not in {'message_list'}}
        details = node.get_details(index=len(self.manager.node_context) - 1)
        details.update(node_id=node.id, runtime_node_id=node.runtime_node_id,
                       up_node_id_list=node.up_node_id_list, tool_recovery=self.details())
        if node.type == 'mcp-node':
            details.pop('tool_params', None)
        answers = [a.to_dict() for a in (node.get_answer_list() or [])]
        try:
            self.store.checkpoint(self.claim, node.id,
                                  encode({'context': context, 'answer_text': node.answer_text, 'details': details, 'answers': answers}),
                                  encode({'context': self.manager.context, 'chat_context': self.manager.chat_context}))
        except Exception as exc:
            from .executor import ToolExecutionFailure
            from .policy import RecoveryPolicy
            mode = RecoveryPolicy.parse(node.node_params.get('recovery_policy')).mode
            state = 'outcome_unknown' if node.type == 'mcp-node' and mode not in {
                'read_only', 'idempotent_write'} else 'failed'
            raise ToolExecutionFailure(state, 'checkpoint') from exc

    def fail(self, node, error=None):
        from .policy import RecoveryPolicy, failure_status, classify_error
        kind = getattr(error, 'error_type', classify_error(error))
        policy = RecoveryPolicy.parse(node.node_params.get('recovery_policy')) if node.type == 'mcp-node' else None
        state = getattr(error, 'status', failure_status(policy, kind) if policy else 'failed')
        try:
            self.store.fail(self.claim, node.id, state, kind)
        finally:
            self.close()

    def close(self):
        self._stop.set()

    def details(self):
        return {'run_id': str(self.run.id), 'generation': self.claim.generation}
