# coding=utf-8
"""Hash runtime dependencies while storing only non-secret identifiers and configuration."""
import json
import os
import subprocess
from pathlib import Path
from django.core.serializers.json import DjangoJSONEncoder
from application.evaluation.dataset import dataset_digest
from application.evaluation.fixtures import LOOKUP_CODE
from application.models import Application
from knowledge.models import Paragraph, Document
from models_provider.models import Model
from system_manage.models.resource_mapping import ResourceMapping


def capture_snapshot(application_id: str) -> dict:
    app = Application.objects.get(pk=application_id)
    if app.tool_enable or app.mcp_enable or app.application_enable or app.skill_tool_ids or app.long_term_enable:
        raise ValueError('Evaluation supports isolated apps without external tools or persistent memory')
    if app.type == 'WORK_FLOW':
        def contains_capability(value):
            if isinstance(value, dict):
                return any((key in ('tool_ids', 'mcp_tool_ids', 'mcp_servers', 'application_ids',
                                   'skill_tool_ids', 'code') and bool(item)) or contains_capability(item)
                           for key, item in value.items())
            return isinstance(value, list) and any(contains_capability(item) for item in value)
        if contains_capability(app.work_flow) or contains_capability(app.default_model_setting):
            raise ValueError('Workflow has external tool capabilities')
        safe_nodes = {'base-node', 'start-node', 'ai-chat-node', 'search-dataset-node', 'reply-node', 'reranker-node'}
        if any(node.get('type') not in safe_nodes for node in app.work_flow.get('nodes', [])):
            raise ValueError('Use the controlled evaluation tool fixture for tool cases')
    # Hash all application fields without exporting embedded tool secrets.
    raw = {field.attname: getattr(app, field.attname) for field in app._meta.fields
           if field.name not in ('create_time', 'update_time', 'publish_time')}
    raw = json.loads(json.dumps(raw, cls=DjangoJSONEncoder))
    knowledge_ids = list(ResourceMapping.objects.filter(source_id=str(app.id), source_type='APPLICATION',
                          target_type='KNOWLEDGE').values_list('target_id', flat=True))
    # Workflow resources can be embedded. Hash workspace model/knowledge state conservatively.
    documents = list(Document.objects.filter(knowledge__workspace_id=app.workspace_id).order_by('id')
                     .values('id', 'is_active', 'update_time'))
    paragraphs = list(Paragraph.objects.filter(knowledge__workspace_id=app.workspace_id).order_by('id')
                      .values('id', 'content', 'is_active', 'update_time'))
    models = list(Model.objects.filter(workspace_id=app.workspace_id).order_by('id')
                  .values('id', 'provider', 'model_name', 'model_type', 'update_time'))
    dependency = json.loads(json.dumps({'application': raw, 'knowledge_ids': knowledge_ids,
                                      'documents': documents, 'paragraphs': paragraphs, 'models': models, 'fixture_code_hash': dataset_digest(LOOKUP_CODE)},
                                     cls=DjangoJSONEncoder))
    root = Path(__file__).resolve().parents[3]
    def git(*args):
        try:
            return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL).decode().strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    sha = git('rev-parse', 'HEAD') or os.environ.get('MAXSB_CODE_SHA', 'unknown')
    diff = git('diff', 'HEAD')
    # Includes untracked implementation files; does not hash credentials or runtime .env files.
    source_files = {}
    for base in (root / 'apps/application/evaluation', root / 'docs/implementation/evaluation'):
        for path in sorted(base.glob('*')):
            if path.suffix in ('.py', '.json'):
                source_files[str(path.relative_to(root))] = path.read_text()
    return {'application_id': str(app.id), 'workspace_id': app.workspace_id,
            'application_type': app.type, 'tool_fixture': 'readonly_lookup_v1',
            'tool_fixture_hash': dataset_digest(LOOKUP_CODE), 'config_hash': dataset_digest(dependency),
            'application_hash': dataset_digest(raw), 'knowledge_hash': dataset_digest(dependency['paragraphs']),
            'knowledge_ids': [str(k) for k in knowledge_ids],
            'application_config': {key: raw[key] for key in ('dialogue_number', 'knowledge_setting', 'model_setting',
                'model_params_setting', 'model_id', 'problem_optimization', 'problem_optimization_prompt', 'work_flow')},
            'models': [m for m in dependency['models'] if m['id'] == str(app.model_id)
                       or m['id'] in json.dumps(app.work_flow)],
            'model_version_status': 'provider model names; immutable revision not reported',
            'model_id': str(app.model_id) if app.model_id else None,
            'model_params': {k: v for k, v in app.model_params_setting.items()
                             if k in ('temperature', 'top_p', 'max_tokens', 'seed')},
            'code_sha': sha, 'local_diff_hash': dataset_digest(diff) if diff is not None else None,
            'evaluation_source_hash': dataset_digest(source_files),
            'image_id': os.environ.get('MAXSB_IMAGE_ID', 'unknown')}
