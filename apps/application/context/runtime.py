# coding=utf-8
"""Online, read-only application of operator-reviewed semantic evidence.

The registry is a server-owned file, never a chat input or application JSON.
Missing/stale records preserve evidence; online requests never pay for judging.
"""
import json
import os
from pathlib import Path
import time

from application.context.processor import process_context
from application.context.reviewed import apply_reviewed_context
from application.context.semantic import digest


class RegistryCache:
    def __init__(self, entries):
        self.entries = entries

    def get(self, key):
        entry = self.entries.get(key)
        if entry is None or not 0 <= time.time() - entry['created'] < 86400:
            return None
        return entry['value']


def model_revision(model_id, workspace_id):
    from models_provider.models import Model
    record = Model.objects.values('id', 'model_name', 'provider', 'update_time').get(
        pk=model_id, workspace_id=workspace_id)
    return digest(record)


def process_runtime_context(items, config=None, *, workspace_id=None, registry_path=None, **kwargs):
    if not (config or {}).get('enabled') or not (config or {}).get('semantic_enabled'):
        return process_context(items, config, **kwargs)
    reason = 'registry_unavailable'
    try:
        if not workspace_id:
            raise ValueError('scope required')
        path = Path(registry_path or os.environ.get('MAXKB_SEMANTIC_REGISTRY',
                                                    '/opt/maxkb/conf/semantic-context.json'))
        with path.open('rb') as stream:
            raw = stream.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('registry too large')
        registry = json.loads(raw)
        if registry['schema'] != 1:
            raise ValueError('unsupported registry')
        scope = registry['scopes'][str(workspace_id)]
        if scope['namespace'] != str(workspace_id) + '/reviewed-context':
            raise ValueError('namespace mismatch')
        bindings = scope['model_bindings']
        if not isinstance(bindings, list) or not 1 <= len(bindings) <= 4:
            raise ValueError('model bindings required')
        reason = 'model_version_changed'
        if any(model_revision(b['id'], workspace_id) != b['revision'] for b in bindings):
            raise ValueError('model drift')
        reason = 'registry_invalid'
        result = apply_reviewed_context(items, config, cache=RegistryCache(scope['entries']),
                                        approvals=scope['approvals'], namespace=scope['namespace'],
                                        versions=scope['versions'], **kwargs)
        audit = result.pop('semantic_application')
        audit['status'] = 'matched' if audit['actual_removed_count'] else 'no_approved_match'
        result['audit']['semantic'] = audit
        return result
    except Exception:
        result = process_context(items, config, **kwargs)
        result['audit']['semantic'] = {'mode': 'reviewed_cache_only', 'status': reason,
                                       'actual_removed_count': 0, 'judge_calls': 0}
        return result
