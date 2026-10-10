# coding=utf-8
"""Deterministic transitions; inactive values survive in events, not active snapshots."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from .types import ChangeSet, MemorySnapshot


def apply_operations(snapshot, operations):
    result = ChangeSet(MemorySnapshot(deepcopy(snapshot.facts), snapshot.version, snapshot.generation))
    facts = result.snapshot.facts
    for op in operations:
        if op.action not in {'add', 'replace', 'revoke', 'pending', 'confirm'}:
            result.rejected.append('invalid_action')
            continue
        if (any(not isinstance(v, str) for v in (op.entity, op.attribute, op.value, op.quote))
                or len(op.entity) > 128 or len(op.attribute) > 128 or len(op.value) > 2048
                or len(op.quote) > 2048):
            result.rejected.append('invalid_length')
            continue
        target = next((f for f in facts if f['id'] == op.target), None)
        if op.action in {'replace', 'revoke', 'confirm'} and target is None:
            result.rejected.append('unknown_target')
            continue
        if op.action in {'add', 'pending'} and (not op.entity.strip() or not op.attribute.strip()):
            result.rejected.append('missing_key')
            continue
        if op.action != 'revoke' and not (op.value.strip() or (op.action == 'confirm' and target)):
            result.rejected.append('missing_value')
            continue
        before = deepcopy(target)
        if op.action == 'revoke' and op.explicit:
            facts.remove(target)
            result.changes.append({'before': before, 'after': {**before, 'status': 'revoked',
                                                              'source': op.source, 'quote': op.quote}})
            continue
        entity = target['entity'] if target else op.entity.strip()
        attribute = target['attribute'] if target else op.attribute.strip()
        value = op.value.strip() or (target['value'] if target else '')
        related = [f for f in facts if f['entity'] == entity and f['attribute'] == attribute]
        if op.action == 'add' and any(f['value'] == value for f in related):
            continue
        replacing = target is not None and op.explicit and op.action in {'replace', 'confirm'}
        if len(facts) >= 100 and not replacing:
            result.rejected.append('capacity')
            continue
        status = 'confirmed'
        if op.action == 'pending' or (related and not replacing):
            status = 'pending'
            for old in related:
                prior = deepcopy(old)
                old['status'] = 'pending'
                result.changes.append({'before': prior, 'after': deepcopy(old)})
        if replacing:
            for old in related:
                facts.remove(old)
                if old['id'] != target['id']:
                    result.changes.append({'before': deepcopy(old), 'after': {**old, 'status': 'superseded'}})
        fact = {'id': target['id'] if replacing else str(uuid4()), 'entity': entity, 'attribute': attribute,
                'value': value, 'status': status, 'source': op.source, 'quote': op.quote,
                'references': op.references, 'version': snapshot.version + 1, 'updated_at': datetime.now(timezone.utc).isoformat()}
        facts.append(fact)
        result.changes.append({'before': before, 'after': deepcopy(fact)})
    return result
