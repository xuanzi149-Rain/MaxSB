# coding=utf-8
"""All persistent reads require an authenticated session identity."""
import hashlib
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from application.models import Chat, ChatRecord, ConversationMemory, ConversationMemoryEvent
from .policy import apply_operations
from .types import MemorySnapshot, TurnTicket


class MemoryConflict(Exception):
    pass


class MemoryDenied(Exception):
    pass


def snapshot(state):
    return MemorySnapshot(state.facts, state.version, state.generation)


class MemoryStore:
    def _chat(self, identity, chat_id, lock=False):
        try:
            UUID(str(chat_id))
        except (ValueError, TypeError):
            raise MemoryDenied('Conversation unavailable') from None
        qs = Chat.objects.filter(pk=chat_id, application_id=identity.application_id,
                                 chat_user_id=identity.chat_user_id, chat_user_type=identity.chat_user_type,
                                 is_deleted=False)
        if lock:
            qs = qs.select_for_update()
        chat = qs.first()
        if chat is None:
            raise MemoryDenied('Conversation unavailable')
        return chat

    def read(self, identity, chat_id):
        self._chat(identity, chat_id)
        state = ConversationMemory.objects.filter(chat_id=chat_id).first()
        return snapshot(state) if state else MemorySnapshot()

    def sources(self, identity, chat_id):
        self._chat(identity, chat_id)
        return list(ConversationMemoryEvent.objects.filter(memory_id=chat_id).exclude(question='').order_by(
            '-created_at').values('id', 'record_id', 'question', 'kind', 'created_at', 'changes')[:100])

    @transaction.atomic
    def begin_turn(self, identity, chat_id, record_id, question):
        self._chat(identity, chat_id, lock=True)
        state, _ = ConversationMemory.objects.get_or_create(chat_id=chat_id)
        record_id = str(UUID(str(record_id)))
        digest = hashlib.sha256(question.encode()).hexdigest()
        old_record = ChatRecord.objects.filter(chat_id=chat_id, id=record_id).first()
        if old_record and old_record.problem_text != question:
            raise MemoryConflict('Send edited text as a new message')
        event = state.events.filter(generation=state.generation, request_id='turn:' + record_id).first()
        if event:
            if event.question_hash != digest:
                raise MemoryConflict('Send edited text as a new message')
            if event.status == 'received':
                if event.created_at > timezone.now() - timedelta(seconds=60):
                    raise MemoryConflict('Memory update in progress')
                event.status = 'failed'
                event.save(update_fields=['status'])
        else:
            event = state.events.create(generation=state.generation, request_id='turn:' + record_id,
                                        record_id=record_id, question=question, question_hash=digest,
                                        base_version=state.version)
        return TurnTicket(str(event.id), str(chat_id), event.base_version, state.generation,
                          event.status, snapshot(state))

    @transaction.atomic
    def commit_turn(self, ticket, changes, usage=None, status='completed'):
        state = ConversationMemory.objects.select_for_update().get(chat_id=ticket.chat_id)
        event = state.events.filter(id=ticket.event_id, generation=ticket.generation).first()
        if not event or state.generation != ticket.generation:
            raise MemoryConflict('Memory cleared')
        if event.status != 'received':
            return snapshot(state)
        if state.version != ticket.version:
            event.status = 'conflict'
            event.usage = usage or {}
            event.save(update_fields=['status', 'usage'])
            raise MemoryConflict('Memory changed')
        if status == 'completed':
            state.facts = changes.snapshot.facts
            state.version += 1
            state.save(update_fields=['facts', 'version', 'updated_at'])
        event.status = status
        event.changes = changes.changes if status == 'completed' else []
        event.usage = usage or {}
        event.result_version = state.version
        event.save(update_fields=['status', 'changes', 'usage', 'result_version'])
        return snapshot(state)

    @transaction.atomic
    def correct(self, identity, chat_id, fact_id, operation, expected_version, request_id):
        self._chat(identity, chat_id, lock=True)
        state, _ = ConversationMemory.objects.get_or_create(chat_id=chat_id)
        request_id = 'edit:' + str(UUID(str(request_id)))
        if state.events.filter(request_id=request_id, generation=state.generation).exists():
            return snapshot(state)
        if state.version != expected_version:
            raise MemoryConflict('Memory changed; refresh')
        event = ConversationMemoryEvent(memory=state, generation=state.generation, request_id=request_id,
                                        kind='manual', status='completed', base_version=state.version,
                                        question=operation.value or '用户撤销条件')
        op = replace(operation, target=fact_id, source=str(event.id), explicit=True, quote=event.question)
        changes = apply_operations(snapshot(state), [op])
        if changes.rejected:
            raise MemoryConflict(changes.rejected[0])
        state.facts = changes.snapshot.facts
        state.version += 1
        state.save(update_fields=['facts', 'version', 'updated_at'])
        event.result_version = state.version
        event.changes = changes.changes
        event.save()
        return snapshot(state)

    @transaction.atomic
    def clear(self, identity, chat_id, expected_version, request_id):
        self._chat(identity, chat_id, lock=True)
        state, _ = ConversationMemory.objects.get_or_create(chat_id=chat_id)
        request_id = 'clear:' + str(UUID(str(request_id)))
        if state.events.filter(request_id=request_id, kind='clear').exists():
            return snapshot(state)
        if state.version != expected_version:
            raise MemoryConflict('Memory changed; refresh')
        state.events.exclude(kind='clear').delete()
        state.facts = []
        state.generation += 1
        state.version += 1
        state.history_since = timezone.now()
        state.save()
        state.events.create(generation=state.generation, request_id=request_id, kind='clear', status='completed',
                            base_version=expected_version, result_version=state.version)
        return snapshot(state)

    def history(self, identity, chat_id, record_id):
        self._chat(identity, chat_id)
        state = ConversationMemory.objects.filter(chat_id=chat_id).first()
        if not state:
            return []
        records = ChatRecord.objects.filter(chat_id=chat_id, create_time__gte=state.history_since).exclude(
            id=record_id).order_by('-create_time', '-id')[:20]
        return [{'id': str(r.id), 'question': r.problem_text, 'answer': r.answer_text} for r in reversed(list(records))]

    def filter_recent(self, identity, chat_id, turns):
        self._chat(identity, chat_id)
        state = ConversationMemory.objects.filter(chat_id=chat_id).first()
        if not state or state.generation == 0:
            return turns
        allowed = {str(pk) for pk in ChatRecord.objects.filter(chat_id=chat_id,
                    create_time__gte=state.history_since).values_list('id', flat=True)}
        return [turn for turn in turns if turn.get('id') in allowed]
