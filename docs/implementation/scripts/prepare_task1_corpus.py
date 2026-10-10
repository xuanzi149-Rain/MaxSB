"""Create dedicated evaluation resources, never overwrite task-0 resources.

Execute using Django shell after reviewing the synthetic corpus. Embedding is deliberately
separate: use the existing document embedding command/service with the returned IDs.
"""
import json
from copy import copy
import uuid
from pathlib import Path
from django.db import transaction
from application.models import Application
from application.evaluation.dataset import dataset_digest
from knowledge.models import Knowledge, Document, Paragraph
from system_manage.models.resource_mapping import ResourceMapping


def prepare(source_application_id, source_knowledge_id):
    source = Application.objects.get(pk=source_application_id)
    source_knowledge = Knowledge.objects.get(pk=source_knowledge_id, workspace_id=source.workspace_id)
    corpus = json.loads((Path(__file__).resolve().parents[1] / 'evaluation/corpus.json').read_text())
    corpus_hash = dataset_digest(corpus)
    if Application.objects.filter(name='任务1评测基线', workspace_id=source.workspace_id).exists():
        raise ValueError('Dedicated baseline already exists; inspect it instead of overwriting')
    mapping = {}
    with transaction.atomic():
        model = copy(source.model)
        model.pk = uuid.uuid4()
        model.name = '任务1评测专用模型'
        model.model_params_form = [*model.model_params_form,
            {'field': 'max_retries', 'default_value': 0},
            {'field': 'stream_usage', 'default_value': True},
            {'field': 'extra_body', 'default_value': {'enable_thinking': False}}]
        model.save(force_insert=True)
        knowledge = Knowledge.objects.create(name='任务1合成评测资料', desc='Synthetic public fixtures; not real policies',
            workspace_id=source.workspace_id, folder=source_knowledge.folder, user=source.user,
            embedding_model=source_knowledge.embedding_model, meta={'evaluation_corpus_hash': corpus_hash})
        for item in corpus['documents']:
            document = Document.objects.create(knowledge=knowledge, name=item['evidence_id'], user=source.user,
                                                char_length=len(item['text']))
            paragraph = Paragraph.objects.create(knowledge=knowledge, document=document, content=item['text'],
                                                  title=item['evidence_id'], position=1)
            mapping[item['evidence_id']] = {'document_id': str(document.pk), 'paragraph_id': str(paragraph.pk)}
        app = Application.objects.create(name='任务1评测基线', workspace_id=source.workspace_id, folder=source.folder,
            user=source.user, model=model, model_params_setting={**source.model_params_setting, 'temperature': 0, 'max_tokens': 2048,
                'max_retries': 0, 'stream_usage': True, 'extra_body': {'enable_thinking': False}},
            dialogue_number=3, knowledge_setting={**source.knowledge_setting, 'top_n': 5, 'similarity': 0.2},
            model_setting={**source.model_setting, 'system': '根据提供的资料回答。保留资料中的方括号证据ID作为引用；资料不足时明确说明，不编造。'})
        ResourceMapping.objects.create(source_type='APPLICATION', target_type='KNOWLEDGE',
                                       source_id=str(app.pk), target_id=str(knowledge.pk))
    return {'application_id': str(app.pk), 'knowledge_id': str(knowledge.pk),
            'embedding_model_id': str(knowledge.embedding_model_id), 'corpus_hash': corpus_hash, 'evidence_map': mapping}
