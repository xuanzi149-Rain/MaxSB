# coding=utf-8
"""Debug-only cache adapter. Its caller must authenticate the debug ChatInfo owner."""
import hashlib
import time
from contextlib import contextmanager
from dataclasses import asdict, replace
from uuid import uuid4
from django.core.cache import cache
from .types import MemorySnapshot, TurnTicket
from .policy import apply_operations
from .store import MemoryConflict, MemoryDenied


class TemporaryMemoryStore:
    def __init__(self, identity, chat_id):
        self.identity, self.chat_id = identity, str(chat_id)
        digest = hashlib.sha256(repr((identity, self.chat_id)).encode()).hexdigest()
        self.key = 'conversation-memory-debug:' + digest

    def _check(self, identity, chat_id):
        if identity != self.identity or str(chat_id) != self.chat_id:
            raise MemoryDenied('Conversation unavailable')

    def _load(self):
        return cache.get(self.key) or {'snapshot': asdict(MemorySnapshot()), 'events': {}, 'clears': []}

    @contextmanager
    def _write(self):
        lock = self.key + ':lock'
        if not cache.add(lock, True, timeout=10):
            raise MemoryConflict('Memory update in progress')
        try:
            data = self._load()
            yield data
            cache.set(self.key, data, timeout=1800)
        finally:
            cache.delete(lock)

    def read(self, identity, chat_id):
        self._check(identity, chat_id)
        return MemorySnapshot(**self._load()['snapshot'])

    def sources(self, identity, chat_id):
        self._check(identity, chat_id)
        return [e for e in self._load()['events'].values() if e.get('question')][-100:]

    def history(self, identity, chat_id, record_id):
        self._check(identity, chat_id)
        return [{'id': e['record_id'], 'question': e['question'], 'answer': ''}
                for e in self.sources(identity, chat_id) if e['record_id'] != str(record_id)][-20:]

    def begin_turn(self, identity, chat_id, record_id, question):
        self._check(identity, chat_id)
        with self._write() as data:
            state = MemorySnapshot(**data['snapshot'])
            key = str(record_id)
            cleared = data.get('cleared_turns', {}).get(key)
            if cleared:
                if cleared != hashlib.sha256(question.encode()).hexdigest():
                    raise MemoryConflict('Send edited text as a new message')
                return TurnTicket('', str(chat_id), state.version, state.generation, 'cleared', state)
            event = data['events'].get(key)
            if event:
                if event['question'] != question:
                    raise MemoryConflict('Send edited text as a new message')
                if event['status'] == 'received':
                    if time.time() - event['time'] < 60:
                        raise MemoryConflict('Memory update in progress')
                    event['status'] = 'failed'
            else:
                event = {'id': str(uuid4()), 'record_id': key, 'question': question, 'kind': 'turn',
                         'status': 'received', 'time': time.time(), 'version': state.version}
                data['events'][key] = event
            return TurnTicket(event['id'], str(chat_id), event['version'], state.generation, event['status'], state)

    def commit_turn(self, ticket, changes, usage=None, status='completed'):
        with self._write() as data:
            state = MemorySnapshot(**data['snapshot'])
            event = next((e for e in data['events'].values() if e['id'] == ticket.event_id), None)
            if not event or state.generation != ticket.generation or state.version != ticket.version:
                raise MemoryConflict('Memory changed')
            if event['status'] == 'completed':
                return state
            if status == 'completed':
                state.facts = changes.snapshot.facts
                state.version += 1
                data['snapshot'] = asdict(state)
            event.update(status=status, usage=usage or {}, changes=changes.changes)
            return state

    def correct(self, identity, chat_id, fact_id, operation, expected_version, request_id):
        self._check(identity, chat_id)
        with self._write() as data:
            state = MemorySnapshot(**data['snapshot'])
            key = 'manual:' + str(request_id)
            if key in data['events']:
                return state
            if state.version != expected_version:
                raise MemoryConflict('Memory changed; refresh')
            source = str(uuid4())
            changes = apply_operations(state, [replace(operation, target=str(fact_id), source=source, explicit=True,
                                                        quote=operation.value or '用户撤销条件')])
            if changes.rejected:
                raise MemoryConflict(changes.rejected[0])
            state = changes.snapshot
            state.version += 1
            data['snapshot'] = asdict(state)
            data['events'][key] = {'id': source, 'record_id': '', 'question': operation.value or '用户撤销条件',
                                   'kind': 'manual', 'changes': changes.changes, 'status': 'completed'}
            return state

    def clear(self, identity, chat_id, expected_version, request_id):
        self._check(identity, chat_id)
        with self._write() as data:
            state = MemorySnapshot(**data['snapshot'])
            if request_id in data['clears']:
                return state
            if state.version != expected_version:
                raise MemoryConflict('Memory changed; refresh')
            state = MemorySnapshot(version=state.version + 1, generation=state.generation + 1)
            tombstones = data.get('cleared_turns', {})
            tombstones.update({e['record_id']: hashlib.sha256(e['question'].encode()).hexdigest()
                               for e in data['events'].values() if e['kind'] == 'turn'})
            data.update(snapshot=asdict(state), cleared_turns=tombstones, events={}, clears=[*data['clears'], request_id])
            return state

    def filter_recent(self, identity, chat_id, turns):
        self._check(identity, chat_id)
        data = self._load()
        if data['snapshot']['generation'] == 0:
            return turns
        allowed = {e['record_id'] for e in data['events'].values()}
        return [turn for turn in turns if turn.get('id') in allowed]
