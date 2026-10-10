# coding=utf-8
import importlib
from unittest.mock import patch
from django.test import TestCase
from application.models import Application, ApplicationFolder
from users.models import User


class RunnerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='eval-user', nick_name='eval-user', password='unused', role='USER')
        folder = ApplicationFolder.objects.create(id='eval-folder', name='eval', workspace_id='eval')
        self.app = Application.objects.create(name='eval', workspace_id='eval', folder=folder, user=self.user)
        self.dataset = {'version': 'test', 'split': 'dev', 'cases': [
            {'case_id': key, 'scenario': 'direct', 'turns': ['q'], 'required_evidence_ids': [],
             'expected_facts': ['a'], 'acceptable_answers': ['a'], 'tool_expectation': None,
             'rubric': {'correct': 'a', 'failure': 'not a'}} for key in ('one', 'two')]}

    def service(self):
        try:
            return importlib.import_module('application.evaluation.service')
        except ImportError:
            self.fail('Missing evaluation service')

    def test_failure_continues_and_reruns_do_not_overwrite(self):
        service = self.service()
        with patch('application.evaluation.service.capture_snapshot', return_value={'config_hash': 'same'}):
            run = service.create_run('eval', str(self.app.id), str(self.user.id), self.dataset)
            second = service.create_run('eval', str(self.app.id), str(self.user.id), self.dataset)
        self.assertNotEqual(run.pk, second.pk)
        def execute(case, snapshot):
            if case['case_id'] == 'one':
                raise RuntimeError('secret-credential-should-not-leak')
            return {'answer': 'a', 'status': 'success', 'elapsed_seconds': 1}
        with patch('application.evaluation.service.capture_snapshot', return_value={'config_hash': 'same'}), \
                patch('application.evaluation.service.execute_case', side_effect=execute):
            service.execute_run(str(run.pk))
            service.execute_run(str(run.pk))
        run.refresh_from_db()
        self.assertEqual(run.status, 'completed')
        self.assertEqual(run.results.count(), 2)
        self.assertEqual(run.results.get(case_id='one').status, 'failed')
        self.assertEqual(run.results.get(case_id='two').status, 'success')
        self.assertNotIn('secret-credential', str(list(run.results.values())))
        second.refresh_from_db()
        self.assertEqual(second.status, 'queued')

    def test_configuration_drift_does_not_execute_cases(self):
        service = self.service()
        with patch('application.evaluation.service.capture_snapshot', return_value={'config_hash': 'old'}):
            run = service.create_run('eval', str(self.app.id), str(self.user.id), self.dataset)
        with patch('application.evaluation.service.capture_snapshot', return_value={'config_hash': 'new'}):
            service.execute_run(str(run.pk))
        run.refresh_from_db()
        self.assertEqual(run.status, 'configuration_drift')
        self.assertEqual(run.results.count(), 0)

    def test_cross_workspace_creation_rejected(self):
        service = self.service()
        with self.assertRaises(Application.DoesNotExist):
            service.create_run('other', str(self.app.id), str(self.user.id), self.dataset)

    def test_mid_last_case_drift_cannot_finalize_as_completed(self):
        service = self.service()
        with patch('application.evaluation.service.capture_snapshot', return_value={'config_hash': 'same'}):
            run = service.create_run('eval', str(self.app.id), str(self.user.id), {**self.dataset, 'cases': self.dataset['cases'][:1]})
        with patch('application.evaluation.service.capture_snapshot', side_effect=[{'config_hash': 'same'}, {'config_hash': 'changed'}]), \
                patch('application.evaluation.service.execute_case', return_value={'status': 'success', 'answer': 'a'}):
            service.execute_run(str(run.pk))
        run.refresh_from_db()
        self.assertEqual(run.status, 'configuration_drift')

    def test_nested_workflow_tools_are_rejected_before_run_creation(self):
        from application.evaluation.snapshot import capture_snapshot
        self.app.type = 'WORK_FLOW'
        self.app.work_flow = {'nodes': [{'type': 'ai-chat-node', 'properties': {'node_data': {'tool_ids': ['unsafe']}}}]}
        self.app.save()
        with self.assertRaises(ValueError):
            capture_snapshot(str(self.app.pk))

    def test_broker_failure_is_visible_and_sync_run_does_not_enqueue(self):
        service = self.service()
        with patch('application.evaluation.service.capture_snapshot', return_value={'config_hash': 'same'}):
            with self.captureOnCommitCallbacks(execute=True), \
                    patch('application.tasks.run_evaluation.delay', side_effect=RuntimeError('broker unavailable')):
                run = service.create_run('eval', str(self.app.id), str(self.user.id), self.dataset)
            run.refresh_from_db()
            self.assertEqual(run.status, 'dispatch_failed')
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                service.create_run('eval', str(self.app.id), str(self.user.id), self.dataset, enqueue=False)
            self.assertEqual(len(callbacks), 0)

    def test_archive_snapshot_requires_valid_packaging_diff_hash(self):
        from application.evaluation.snapshot import capture_snapshot
        self.app.type = 'WORK_FLOW'
        self.app.work_flow = {'nodes': [{'type': 'search-knowledge-node'}]}
        self.app.save()
        with patch('application.evaluation.snapshot.subprocess.check_output', side_effect=OSError), \
                patch.dict('os.environ', {'MAXSB_LOCAL_DIFF_HASH': 'a' * 64}):
            self.assertEqual(capture_snapshot(str(self.app.pk))['local_diff_hash'], 'a' * 64)
        with patch('application.evaluation.snapshot.subprocess.check_output', side_effect=OSError), \
                patch.dict('os.environ', {'MAXSB_LOCAL_DIFF_HASH': 'unknown'}):
            self.assertIsNone(capture_snapshot(str(self.app.pk))['local_diff_hash'])
