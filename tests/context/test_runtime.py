"""Online semantic registry is optional, scoped, versioned and read-only."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from application.context.semantic import digest, evidence
from application.context.reviewed import pair_key
from application.context.runtime import process_runtime_context


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'registry.json'
        self.rows = [dict(id=str(i), document_id=str(i), knowledge_id='k', title='规则', content=c, meta={})
                     for i, c in enumerate(['阅览室禁止吸烟。', '阅览室内不得吸烟。'])]
        a, b = sorted(map(evidence, self.rows), key=digest)
        def judge(a, b):
            return dict(scope_match=True, a_entails_b=True, b_entails_a=True, conflict=False, uncertain=False,
                        reason='同义', a_quotes=[a['content']], b_quotes=[b['content']])
        value = {'forward': judge(a, b), 'backward': judge(b, a)}
        versions = {'judge': 'j', 'embedding': 'e'}
        key = pair_key(a, b, 'w/reviewed-context', versions)
        self.scope = dict(namespace='w/reviewed-context', versions=versions,
                          model_bindings=[{'id': 'm', 'revision': 'rev'}],
                          approvals={key: digest(value)}, entries={key: {'value': value, 'created': time.time()}})
        self.save()
        self.config = {'enabled': True, 'semantic_enabled': True}

    def save(self):
        self.path.write_text(json.dumps({'schema': 1, 'scopes': {'w': self.scope}}))

    def run_policy(self, **kwargs):
        params = {'workspace_id': 'w', 'registry_path': self.path}
        params.update(kwargs)
        with patch('application.context.runtime.model_revision', return_value='rev'):
            return process_runtime_context(self.rows, self.config, **params)

    def test_scoped_fresh_approval_applies_and_audits(self):
        result = self.run_policy()
        self.assertEqual(len(result['retained']), 1)
        self.assertEqual(result['audit']['semantic']['actual_removed_count'], 1)
        self.assertEqual(result['audit']['semantic']['judge_calls'], 0)

    def test_wrong_workspace_missing_file_and_expiry_keep_both(self):
        self.assertEqual(len(self.run_policy(workspace_id='other')['retained']), 2)
        self.assertEqual(len(self.run_policy(registry_path=self.path.with_name('absent'))['retained']), 2)
        for entry in self.scope['entries'].values():
            entry['created'] -= 86401
        self.save()
        self.assertEqual(len(self.run_policy()['retained']), 2)

    def test_model_drift_and_unbound_registry_keep_both(self):
        with patch('application.context.runtime.model_revision', return_value='changed'):
            result = process_runtime_context(self.rows, self.config, workspace_id='w', registry_path=self.path)
        self.assertEqual(len(result['retained']), 2)
        self.scope['model_bindings'] = []
        self.save()
        self.assertEqual(len(self.run_policy()['retained']), 2)

    def test_disabled_never_reads_registry_or_models(self):
        with patch('application.context.runtime.model_revision', side_effect=AssertionError('no read')):
            result = process_runtime_context(self.rows, {'enabled': True}, workspace_id='w', registry_path=self.path)
        self.assertEqual(len(result['retained']), 2)
        self.assertNotIn('semantic', result['audit'])

    def test_corrupt_registry_fail_closed_without_private_details(self):
        self.path.write_text('private-invalid-json')
        result = self.run_policy()
        self.assertEqual(len(result['retained']), 2)
        self.assertNotIn('private-invalid-json', str(result))
