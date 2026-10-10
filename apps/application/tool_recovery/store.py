# coding=utf-8
"""Short, fenced transactions around remote calls. Never hold a lock over I/O."""
import json
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from application.models import Chat, ChatRecord, ToolRun, ToolStep, ToolAttempt
from .types import Claim, RecoveryConflict, RecoveryDenied


def bounded(value, maximum=1024 * 1024):
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > maximum:
        raise ValueError('Recovery snapshot is too large')
    return value


class RecoveryStore:
    def _chat(self, identity, chat_id):
        chat = Chat.objects.filter(id=chat_id, application_id=identity.application_id,
                                   chat_user_id=identity.chat_user_id, chat_user_type=identity.chat_user_type,
                                   is_deleted=False).first()
        if chat is None:
            raise RecoveryDenied('Run unavailable')
        return chat

    def read(self, identity, run_id):
        run = ToolRun.objects.filter(id=run_id).first()
        if run is None:
            raise RecoveryDenied('Run unavailable')
        self._chat(identity, run.chat_id)
        return run

    def create(self, identity, chat_id, record_id, snapshot):
        chat = self._chat(identity, chat_id)
        return ToolRun.objects.create(chat=chat, record_id=record_id, snapshot=bounded(snapshot),
                                      lease_until=timezone.now() + timedelta(seconds=60))

    def initial_claim(self, run):
        return Claim(str(run.id), run.generation)

    def _locked(self, claim):
        run = ToolRun.objects.select_for_update().get(id=claim.run_id)
        if run.generation != claim.generation or run.status != 'running' or run.lease_until <= timezone.now():
            raise RecoveryConflict('Execution claim expired or replaced')
        if not Chat.objects.filter(id=run.chat_id, is_deleted=False).exists():
            raise RecoveryDenied('Run unavailable')
        return run

    @transaction.atomic
    def heartbeat(self, claim):
        run = self._locked(claim)
        run.lease_until = timezone.now() + timedelta(seconds=60)
        run.save(update_fields=['lease_until'])

    def claim(self, identity, run_id, request_id, expected_version):
        self.read(identity, run_id)
        # Unknown conversion must commit even when this request is rejected.
        self.reconcile_expired(run_id)
        with transaction.atomic():
            run = ToolRun.objects.select_for_update().get(id=run_id)
            if request_id in run.requests:
                return Claim(str(run.id), run.requests[request_id], False)
            if (run.version != expected_version or run.status != 'failed' or run.resumes >= 3 or
                    timezone.now() - run.created_at > timedelta(hours=24)):
                raise RecoveryConflict('Run cannot resume; refresh its state')
            step = run.steps.filter(node_id=run.failed_node).first()
            not_started = step is not None and step.error_type == 'not_started' and not step.attempts.exists()
            if step is None or (not not_started and (step.node_type != 'mcp-node' or step.error_type not in {'timeout', 'transient', 'checkpoint', 'confirmed'})):
                raise RecoveryConflict('This failure cannot resume')
            mode = step.policy.get('mode', 'unknown')
            if not not_started and mode not in {'read_only', 'idempotent_write'} and step.error_type != 'confirmed':
                raise RecoveryConflict('Tool outcome requires manager confirmation')
            if (mode == 'idempotent_write' and timezone.now() - run.created_at >
                    timedelta(hours=step.policy.get('retention_hours', 24))):
                raise RecoveryConflict('Tool idempotency window expired')
            run.resumes += 1
            run.version += 1
            run.generation += 1
            run.status = 'running'
            run.requests[request_id] = run.generation
            run.lease_until = timezone.now() + timedelta(seconds=60)
            run.save()
            return Claim(str(run.id), run.generation)

    @transaction.atomic
    def reconcile_expired(self, run_id):
        run = ToolRun.objects.select_for_update().get(id=run_id)
        if run.status != 'running' or run.lease_until > timezone.now():
            return
        step = run.steps.filter(status='running').first()
        expected = set(run.snapshot.get('node_ids', []))
        completed = set(run.steps.filter(status='succeeded').values_list('node_id', flat=True))
        if expected and completed == expected:
            payload = checkpoint_payload(run)
            ChatRecord.objects.update_or_create(id=run.record_id, defaults={
                'chat_id': run.chat_id, 'problem_text': run.snapshot['params'].get('question', '')[:10240],
                'index': ChatRecord.objects.filter(chat_id=run.chat_id).exclude(id=run.record_id).count(),
                **payload,
            })
            from django.core.cache import cache
            from common.constants.cache_version import Cache_Version
            transaction.on_commit(lambda: cache.delete(
                Cache_Version.CHAT.get_key(key=str(run.chat_id)), version=Cache_Version.CHAT_INFO.get_version()))
            run.status = 'succeeded'
            run.version += 1
            run.generation += 1
            run.save()
            return
        if step is None:
            pending = next((n for n in run.snapshot.get('node_order', []) if n['id'] not in completed), None)
            if pending:
                step, _ = run.steps.get_or_create(node_id=pending['id'], defaults={'node_type': pending['type']})
        run.generation += 1
        run.version += 1
        run.status = 'failed'
        if step:
            pending_dispatch = step.status == 'pending'
            mode = step.policy.get('mode', 'unknown')
            step.status = 'outcome_unknown' if step.node_type == 'mcp-node' and mode not in {
                'read_only', 'idempotent_write'} else 'failed'
            step.error_type = 'timeout'
            if not step.attempts.exists() and (step.node_type == 'mcp-node' or pending_dispatch):
                step.status, step.error_type = 'failed', 'not_started'
            step.save()
            step.attempts.filter(status='running').update(status=step.status, error_type='timeout', ended_at=timezone.now())
            run.status, run.failed_node = step.status, step.node_id
        run.save()

    @transaction.atomic
    def begin_step(self, claim, node_id, node_type):
        run = self._locked(claim)
        step, _ = ToolStep.objects.get_or_create(run=run, node_id=node_id, defaults={'node_type': node_type})
        if step.status != 'succeeded':
            step.status = 'running'
            step.save()
        return step

    @transaction.atomic
    def begin_attempt(self, claim, node_id, inputs, policy):
        run = self._locked(claim)
        step = run.steps.get(node_id=node_id)
        if step.status == 'succeeded':
            raise RecoveryConflict('Completed step cannot execute again')
        if not step.input_saved:
            total = sum(len(json.dumps([s.inputs, s.output, s.variables]).encode()) for s in run.steps.all())
            if total + len(json.dumps(inputs).encode()) > 10 * 1024 * 1024:
                raise ValueError('Run input budget exceeded')
            step.inputs, step.policy = bounded(inputs), bounded(policy)
            step.input_saved = True
        step.status = 'running'
        step.save()
        return ToolAttempt.objects.create(step=step, generation=claim.generation)

    @transaction.atomic
    def finish_attempt(self, claim, attempt_id, status, error_type='', wait_seconds=0):
        self._locked(claim)
        attempt = ToolAttempt.objects.select_for_update().get(id=attempt_id, step__run_id=claim.run_id,
                                                             generation=claim.generation)
        if attempt.status != 'running':
            raise RecoveryConflict('Attempt already finished')
        attempt.status, attempt.error_type = status, error_type
        attempt.ended_at, attempt.wait_seconds = timezone.now(), wait_seconds
        attempt.save()

    @transaction.atomic
    def checkpoint(self, claim, node_id, output, variables):
        run = self._locked(claim)
        bounded(output)
        bounded(variables)
        total = sum(len(json.dumps([s.inputs, s.output, s.variables]).encode()) for s in run.steps.all())
        if total + len(json.dumps([output, variables]).encode()) > 10 * 1024 * 1024:
            raise ValueError('Run checkpoint budget exceeded')
        step = run.steps.get(node_id=node_id)
        step.output, step.variables, step.status, step.error_type = output, variables, 'succeeded', ''
        step.save()

    @transaction.atomic
    def fail(self, claim, node_id, status, error_type):
        run = self._locked(claim)
        run.steps.filter(node_id=node_id).update(status=status, error_type=error_type)
        run.status, run.failed_node = status, node_id
        run.version += 1
        run.save()

    @transaction.atomic
    def complete(self, claim):
        run = self._locked(claim)
        run.status = 'succeeded'
        run.version += 1
        run.save()

    @transaction.atomic
    def resolve(self, run_id, actor, request_id, expected_version, conclusion, evidence, output=None):
        run = ToolRun.objects.select_for_update().get(id=run_id)
        if any(r['request_id'] == request_id for r in run.resolution):
            return run
        if run.status != 'outcome_unknown' or run.version != expected_version:
            raise RecoveryConflict('Refresh the unknown outcome before confirming')
        step = run.steps.get(node_id=run.failed_node)
        if conclusion not in {'executed', 'not_executed'} or len(evidence.strip()) < 10:
            raise ValueError('A verified operation result or termination evidence is required')
        if conclusion == 'executed':
            if not isinstance(output, list) or not all(isinstance(x, str) for x in output):
                raise ValueError('Confirmed MCP result must be an array of text contents')
            bounded(output)
        step.output = {'confirmed_result': output} if conclusion == 'executed' else {}
        step.status, step.error_type = 'failed', 'confirmed'
        step.save()
        run.resolution.append({'request_id': request_id, 'actor': str(actor), 'conclusion': conclusion,
                               'evidence': evidence, 'time': timezone.now().isoformat()})
        run.status, run.version = 'failed', run.version + 1
        run.save()
        return run

    @transaction.atomic
    def persist_record(self, claim, chat_info, record):
        run = ToolRun.objects.select_for_update().get(id=claim.run_id)
        if run.generation != claim.generation or not Chat.objects.filter(id=run.chat_id, is_deleted=False).exists():
            return False
        if run.snapshot.get('saved_generation') == claim.generation:
            return False
        if run.status == 'running':
            if run.lease_until <= timezone.now():
                return False
            expected = set(run.snapshot.get('node_ids', []))
            completed = set(run.steps.filter(status='succeeded').values_list('node_id', flat=True))
            if not expected or completed != expected:
                return False
            run.status = 'succeeded'
            run.version += 1
        chat_info.append_chat_record(record)
        run.snapshot['saved_generation'] = claim.generation
        run.save()
        return True


def checkpoint_payload(run):
    steps = list(run.steps.filter(status='succeeded').order_by('id'))
    details = {s.output['details']['runtime_node_id']: s.output['details'] for s in steps if s.output.get('details')}
    answers = [s.output.get('answers', []) for s in steps if s.output.get('answers')]
    return {'answer_text': '\n\n'.join(str(s.output.get('answer_text')) for s in steps if s.output.get('answer_text')),
            'answer_text_list': answers, 'details': details}
