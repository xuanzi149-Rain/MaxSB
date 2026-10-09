"""Migrate the six user-approved fixture meanings into a separate local demo.

Only exact copies of approved source text/title may be rebound to new demo IDs.
Keep original cached timestamps; this is not a new model judgement or TTL renewal.
"""
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from copy import deepcopy
from contextlib import closing



def main(root, cache_path, output):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maxkb.settings')
    import django
    django.setup()
    from django.db import transaction
    from application.models import Application
    from application.serializers.application import ApplicationOperateSerializer
    from application.context.runtime import model_revision
    from application.context.semantic import digest, evidence, validate_judgement, signature, decision, PairCache
    from application.context.reviewed import pair_key
    from application.chat_pipeline.step.search_dataset_step.impl.base_search_dataset_step import reset_meta
    from knowledge.models import Knowledge, Document, Paragraph
    from knowledge.task.embedding import embedding_by_document
    from system_manage.models.resource_mapping import ResourceMapping
    from django.core.management import call_command

    output.mkdir(parents=True, exist_ok=False)
    fixture = json.loads((root / 'docs/implementation/evaluation/task2-semantic-dev-v1.json').read_text())
    approval = json.loads((root / 'docs/implementation/evaluation/task2-semantic-approved-v1.json').read_text())
    snapshot = json.loads(Path('/tmp/maxsb-task2/task2-results/verified-dev-v1/off.json').read_text())['snapshot']
    source = Application.objects.get(pk=snapshot['application_id'])
    old_knowledge = Knowledge.objects.get(pk=snapshot['knowledge_ids'][0])
    workspace = source.workspace_id
    namespace = workspace + '/reviewed-context'
    if Application.objects.filter(name='任务2同义去重验证', workspace_id=workspace).exists():
        raise ValueError('Demo already exists; do not duplicate or overwrite')
    expected = next(m for m in snapshot['models'] if m['id'] == snapshot['model_id'])
    params = {**snapshot['application_config']['model_params_setting'], 'max_tokens': 768}
    versions = {'judge': digest({'model': expected, 'params': params,
                                 'record_updated': str(source.model.update_time)}),
                'embedding': digest({'id': str(old_knowledge.embedding_model_id),
                                     'name': old_knowledge.embedding_model.model_name,
                                     'updated': str(old_knowledge.embedding_model.update_time)})}
    if versions != approval['versions']:
        raise ValueError('Original reviewed model versions changed')
    prepared = []
    with closing(sqlite3.connect(cache_path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        for case in fixture['cases']:
            if case['case_id'] not in approval['case_ids']:
                continue
            key = pair_key(*case['items'], approval['namespace'], approval['versions'])
            row = db.execute('SELECT value,created FROM pairs WHERE key=?', (key,)).fetchone()
            if row is None or not 0 <= time.time() - row[1] < 86400:
                raise ValueError('Original reviewed cache expired')
            value = json.loads(row[0])
            if digest(value) != approval['approvals'][key]:
                raise ValueError('Original review changed')
            prepared.append((case, key, value, row[1]))
    if len(prepared) != 6:
        raise ValueError('Only the exact six approved pairs are authorized')
    review = {'authorization': 'User authorized local integration of the six approved examples; exact copy migration',
              'namespace': namespace, 'versions': approval['versions'],
              'model_bindings': [{'id': str(mid), 'revision': model_revision(mid, workspace)}
                                 for mid in (source.model_id, old_knowledge.embedding_model_id)],
              'approvals': {}, 'provenance': []}
    destination_cache = PairCache(output / 'reviewed-cache.sqlite')
    with transaction.atomic():
        knowledge = Knowledge.objects.create(name='任务2已审核同义示例', workspace_id=workspace,
            desc='Six synthetic examples explicitly approved by user; separate from baseline corpora',
            user=source.user, folder=old_knowledge.folder, embedding_model=old_knowledge.embedding_model)
        documents = []
        for case, original_key, value, created in prepared:
            document = Document.objects.create(knowledge=knowledge, name=case['case_id'], user=source.user,
                                               char_length=sum(len(p['content']) for p in case['items']))
            documents.append(document)
            mapping = {}
            for index, item in enumerate(case['items']):
                paragraph = Paragraph.objects.create(knowledge=knowledge, document=document, title=item['title'],
                                                      content=item['content'], position=index + 1)
                current = {'id': str(paragraph.pk), 'document_id': str(document.pk), 'knowledge_id': str(knowledge.pk),
                           'title': paragraph.title, 'content': paragraph.content, 'meta': reset_meta(document.meta)}
                if current['content'] != item['content'] or current['title'] != item['title']:
                    raise ValueError('Migration must not rewrite reviewed evidence')
                mapping[item['id']] = current
            original = sorted(map(evidence, case['items']), key=digest)
            canonical = sorted(map(evidence, mapping.values()), key=digest)
            if canonical[0]['id'] != mapping[original[0]['id']]['id']:
                value = {'forward': value['backward'], 'backward': value['forward']}
            forward = validate_judgement(value['forward'], *canonical)
            backward = validate_judgement(value['backward'], *canonical[::-1])
            if decision(forward) != 'review_equivalent' or signature(forward) != signature(backward, reverse=True):
                raise ValueError('Unapproved relation cannot migrate')
            key = pair_key(*canonical, namespace, approval['versions'])
            destination_cache.set(key, value, now=created)
            review['approvals'][key] = digest(value)
            review['provenance'].append({'case_id': case['case_id'], 'original_pair_key': original_key,
                                        'new_pair_key': key, 'items': canonical, 'original_created': created,
                                        'scope_change': 'isolated demo copies, normalized runtime metadata and real IDs'})
        app = Application.objects.create(name='任务2同义去重验证', workspace_id=workspace, user=source.user,
            folder=source.folder, model=source.model, model_params_setting=deepcopy(source.model_params_setting),
            dialogue_number=0, knowledge_setting={**source.knowledge_setting, 'top_n': 2, 'similarity': 0,
                'context_policy': {'enabled': True, 'semantic_enabled': True, 'token_budget': 2048,
                                   'similarity_threshold': .95}},
            model_setting={**source.model_setting, 'system': '根据提供资料简洁回答，不编造，保留原意。'})
        ResourceMapping.objects.create(source_type='APPLICATION', target_type='KNOWLEDGE',
                                       source_id=str(app.pk), target_id=str(knowledge.pk))
    # Embedding uses the existing local model, without paid semantic judging.
    for document in documents:
        embedding_by_document(str(document.pk), str(knowledge.embedding_model_id))
    (output / 'review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2))
    call_command('publish_context_review', review=output / 'review.json', cache=output / 'reviewed-cache.sqlite',
                 workspace=workspace, output=Path('/opt/maxkb/conf/semantic-context.json'))
    serializer = ApplicationOperateSerializer(data={'application_id': str(app.pk), 'workspace_id': workspace,
                                                     'user_id': str(app.user_id)})
    serializer.publish({}, with_valid=True)
    resources = {'application_id': str(app.pk), 'knowledge_id': str(knowledge.pk), 'name': app.name,
                 'approved_pairs': 6, 'paid_judgement_calls': 0}
    (output / 'resources.json').write_text(json.dumps(resources, ensure_ascii=False, indent=2))
    print(json.dumps(resources, ensure_ascii=False))


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
