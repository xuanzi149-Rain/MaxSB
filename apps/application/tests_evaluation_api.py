# coding=utf-8
import importlib
import json
from types import SimpleNamespace
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from application.models import Application, ApplicationFolder
from users.models import User


class EvaluationAPITests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create(username='api-eval', nick_name='api-eval', password='unused', role='USER')
        folder = ApplicationFolder.objects.create(id='api-eval', name='eval', workspace_id='w')
        self.app = Application.objects.create(name='eval', workspace_id='w', folder=folder, user=self.user)

    def views(self):
        try:
            return importlib.import_module('application.views.evaluation')
        except ImportError:
            self.fail('Missing evaluation API')

    def request(self, method='get', data=None, roles=None, permissions=None):
        request = getattr(self.factory, method)('/', data or {}, format='json')
        force_authenticate(request, user=self.user,
                           token=SimpleNamespace(role_list=roles or [], permission_list=permissions or []))
        return request

    def test_no_permissions_cannot_read_or_create(self):
        view = self.views().EvaluationRuns.as_view()
        for method in ('get', 'post'):
            response = view(self.request(method), workspace_id='w', application_id=str(self.app.pk))
            self.assertEqual(response.status_code, 403)

    def test_unsupported_application_returns_validation_error(self):
        from application.models import EvaluationRun
        self.app.long_term_enable = True
        self.app.save(update_fields=['long_term_enable'])
        response = self.views().EvaluationRuns.as_view()(
            self.request('post', {'dataset_version': 'dev-v1'}, roles=['ADMIN']),
            workspace_id='w', application_id=str(self.app.pk))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(EvaluationRun.objects.exists())

    def test_admin_cannot_read_run_via_wrong_workspace_or_application(self):
        from application.models import EvaluationRun
        run = EvaluationRun.objects.create(application=self.app, workspace_id='w', user_id=str(self.user.pk),
                                            dataset_hash='x')
        view = self.views().EvaluationDetail.as_view()
        response = view(self.request(roles=['ADMIN']), workspace_id='other', application_id=str(self.app.pk),
                        run_id=str(run.pk))
        self.assertEqual(response.status_code, 404)

    def test_comparison_rejects_other_application_and_unfinished_run(self):
        from application.models import EvaluationRun
        other = Application.objects.create(name='other', workspace_id='w', folder=self.app.folder)
        left = EvaluationRun.objects.create(application=self.app, workspace_id='w', user_id=str(self.user.pk),
                                             dataset_hash='x', status='completed')
        right = EvaluationRun.objects.create(application=other, workspace_id='w', user_id=str(self.user.pk),
                                              dataset_hash='x', status='completed')
        view = self.views().EvaluationCompare.as_view()
        response = view(self.request(data={'left': str(left.pk), 'right': str(right.pk)}, roles=['ADMIN']),
                        workspace_id='w', application_id=str(self.app.pk))
        self.assertEqual(response.status_code, 404)
        left.status = 'running'
        left.save()
        response = view(self.request(data={'left': str(left.pk), 'right': str(left.pk)}, roles=['ADMIN']),
                        workspace_id='w', application_id=str(self.app.pk))
        self.assertEqual(response.status_code, 400)

    def test_read_permission_cannot_review(self):
        from common.constants.permission_constants import PermissionConstants
        permission = PermissionConstants.APPLICATION_READ.get_workspace_application_permission()(
            None, {'workspace_id': 'w', 'application_id': str(self.app.pk)})
        response = self.views().EvaluationReview.as_view()(self.request('put', {'correct': True},
                                                          permissions=[permission]), workspace_id='w',
                        application_id=str(self.app.pk), run_id='00000000-0000-0000-0000-000000000001', case_id='a')
        self.assertEqual(response.status_code, 403)

    def test_human_citation_review_updates_report_and_keeps_audit_history(self):
        from application.models import EvaluationRun, EvaluationCaseResult
        run = EvaluationRun.objects.create(application=self.app, workspace_id='w', user_id=str(self.user.pk),
            dataset_hash='x', status='completed', dataset={'version': 'v1', 'cases': [{'case_id': 'a'}]})
        row = EvaluationCaseResult.objects.create(run=run, case_id='a', status='success',
            result={'case_id': 'a', 'status': 'success', 'answer': 'answer'})
        kwargs = {'workspace_id': 'w', 'application_id': str(self.app.pk), 'run_id': str(run.pk), 'case_id': 'a'}
        for correct in (True, False):
            response = self.views().EvaluationReview.as_view()(self.request('put', {
                'correct': correct, 'reason': 'manual rubric review', 'citation_total': 2, 'citation_supported': 1,
                'reviewer': 'forged-user'}, roles=['ADMIN']), **kwargs)
            self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.review['reviewer'], str(self.user.pk))
        self.assertEqual(len(row.review_history), 1)
        self.assertEqual(row.review_history[0]['correct'], True)
        response = self.views().EvaluationDetail.as_view()(self.request(roles=['ADMIN']),
            workspace_id='w', application_id=str(self.app.pk), run_id=str(run.pk))
        payload = json.loads(response.content)['data']
        self.assertEqual(payload['summary']['citation_accuracy'], .5)
        self.assertEqual(payload['summary']['accuracy'], 0)

    def test_routing_strategy_requires_enabled_node_and_freezes_role(self):
        from application.evaluation.service import create_run
        from unittest.mock import patch
        snapshot = {'application_config': {'work_flow': {'nodes': []}}}
        with patch('application.evaluation.service.capture_snapshot', return_value=snapshot):
            with self.assertRaises(ValueError):
                create_run('w', str(self.app.pk), str(self.user.pk), {}, enqueue=False, routing_strategy='low')
        snapshot['application_config']['work_flow']['nodes'] = [
            {'properties': {'node_data': {'model_routing': {'enabled': True}}}}]
        with patch('application.evaluation.service.capture_snapshot', return_value=snapshot):
            run = create_run('w', str(self.app.pk), str(self.user.pk), {}, enqueue=False, routing_strategy='low')
        self.assertEqual(run.snapshot['routing_strategy'], 'low')

    def test_routing_comparison_rejects_wrong_roles(self):
        from application.models import EvaluationRun
        runs = [EvaluationRun.objects.create(application=self.app, workspace_id='w', user_id=str(self.user.pk),
            dataset_hash='x', status='completed', snapshot={'routing_strategy': role}) for role in ('low', 'high', 'high')]
        response = self.views().EvaluationCompare.as_view()(self.request(data={
            'left': str(runs[0].pk), 'right': str(runs[1].pk), 'routing': str(runs[2].pk)}, roles=['ADMIN']),
            workspace_id='w', application_id=str(self.app.pk))
        self.assertEqual(response.status_code, 400)
