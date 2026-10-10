# coding=utf-8
"""Application-scoped evaluation management with server-side resource checks."""
import json
from pathlib import Path
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from common.exception.app_exception import AppUnauthorizedFailed
from rest_framework.views import APIView
from application.models import Application, EvaluationRun, EvaluationCaseResult
from application.evaluation.compare import compare_runs
from application.evaluation.dataset import dataset_digest, validate_dataset
from application.evaluation.metrics import summarize
from application.evaluation.service import create_run, reconcile_interrupted, TERMINAL
from common.auth import TokenAuth
from common.auth.authentication import get_is_permissions
from common.constants.permission_constants import PermissionConstants, RoleConstants
from common.result import result

DATA_ROOT = Path(__file__).resolve().parents[3] / 'docs/implementation/evaluation'


def authorize(request, workspace_id, application_id, write=False):
    if request.auth is None:
        raise AppUnauthorizedFailed(403, 'Authentication required')
    permission = PermissionConstants.APPLICATION_EDIT if write else PermissionConstants.APPLICATION_READ
    allowed = get_is_permissions(request, workspace_id=workspace_id, application_id=application_id)(
        permission.get_workspace_application_permission(), permission.get_workspace_permission_workspace_manage_role(),
        RoleConstants.WORKSPACE_MANAGE.get_workspace_role(), RoleConstants.ADMIN)
    if not allowed:
        raise AppUnauthorizedFailed(403, 'Application permission required')
    return get_object_or_404(Application, pk=application_id, workspace_id=workspace_id)


def scoped_run(workspace_id, application_id, run_id):
    return get_object_or_404(EvaluationRun, pk=run_id, workspace_id=workspace_id, application_id=application_id)


def run_data(run, detail=False):
    rows = [{**row.result, 'review': row.review} for row in run.results.order_by('case_id')]
    data = {'run_id': str(run.pk), 'status': run.status, 'dataset_version': run.dataset.get('version'),
            'dataset_hash': run.dataset_hash, 'config_hash': run.snapshot.get('config_hash'),
            'created_at': run.create_time, 'started_at': run.started_at, 'finished_at': run.finished_at,
            'progress': len(rows), 'total': len(run.dataset.get('cases', [])), 'summary': summarize(rows, total_cases=len(run.dataset.get('cases', []))),
            'error': run.error}
    if detail:
        data.update(snapshot={k: v for k, v in run.snapshot.items() if k not in ('user_id', 'application_config')}, cases=rows,
                    questions=run.dataset.get('cases', []))
    return data


class CreateRunInput(serializers.Serializer):
    routing_strategy = serializers.ChoiceField(choices=['low', 'high', 'routing'], required=False)
    dataset_version = serializers.ChoiceField(choices=['dev-v1', 'frozen-v1'])


class ReviewInput(serializers.Serializer):
    correct = serializers.BooleanField()
    reason = serializers.CharField(max_length=2000)
    citation_total = serializers.IntegerField(min_value=0, required=False)
    citation_supported = serializers.IntegerField(min_value=0, required=False)

    def validate(self, attrs):
        total, supported = attrs.get('citation_total'), attrs.get('citation_supported')
        if (total is None) != (supported is None) or (total is not None and supported > total):
            raise serializers.ValidationError('Provide valid citation counts')
        return attrs


class EvaluationRuns(APIView):
    authentication_classes = [TokenAuth]

    def get(self, request, workspace_id, application_id):
        authorize(request, workspace_id, application_id)
        reconcile_interrupted()
        runs = EvaluationRun.objects.filter(workspace_id=workspace_id, application_id=application_id).order_by('-create_time')
        return result.success([run_data(run) for run in runs[:100]])

    def post(self, request, workspace_id, application_id):
        authorize(request, workspace_id, application_id, write=True)
        data = CreateRunInput(data=request.data)
        data.is_valid(raise_exception=True)
        version = data.validated_data['dataset_version']
        dataset = json.loads((DATA_ROOT / (version + '.json')).read_text())
        corpus = json.loads((DATA_ROOT / 'corpus.json').read_text())
        manifest = json.loads((DATA_ROOT / 'manifest.json').read_text())
        validate_dataset(dataset, corpus)
        if dataset_digest(dataset) != manifest['datasets'][version] or dataset_digest(corpus) != manifest['corpus_hash']:
            raise ValidationError('Dataset or corpus differs from sealed manifest')
        if dataset['split'] == 'frozen' and manifest.get('rubric_review', {}).get('status') != 'reviewed':
            raise ValidationError('Frozen dataset requires rubric review before baseline execution')
        try:
            run = create_run(workspace_id, application_id, str(request.user.pk), dataset,
                             routing_strategy=data.validated_data.get('routing_strategy'))
        except ValueError as exc:
            return result.error(str(exc), response_status=400)
        return result.success(run_data(run))


class EvaluationDetail(APIView):
    authentication_classes = [TokenAuth]

    def get(self, request, workspace_id, application_id, run_id, case_id=None):
        authorize(request, workspace_id, application_id)
        run = scoped_run(workspace_id, application_id, run_id)
        if case_id is not None:
            row = get_object_or_404(EvaluationCaseResult, run=run, case_id=case_id)
            return result.success({**row.result, 'review': row.review, 'review_history': row.review_history})
        return result.success(run_data(run, detail=True))


class EvaluationReview(APIView):
    authentication_classes = [TokenAuth]

    def put(self, request, workspace_id, application_id, run_id, case_id):
        authorize(request, workspace_id, application_id, write=True)
        run = scoped_run(workspace_id, application_id, run_id)
        data = ReviewInput(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            row = get_object_or_404(EvaluationCaseResult.objects.select_for_update(), run=run, case_id=case_id)
            if row.review:
                row.review_history = [*row.review_history, row.review]
            row.review = {**data.validated_data, 'reviewer': str(request.user.pk),
                          'reviewed_at': timezone.now().isoformat(), 'rubric_version': run.dataset.get('version')}
            row.save(update_fields=['review', 'review_history', 'update_time'])
        return result.success(row.review)


class EvaluationCompare(APIView):
    authentication_classes = [TokenAuth]

    def get(self, request, workspace_id, application_id):
        authorize(request, workspace_id, application_id)
        left = scoped_run(workspace_id, application_id, request.query_params.get('left'))
        right = scoped_run(workspace_id, application_id, request.query_params.get('right'))
        if left.status not in TERMINAL or right.status not in TERMINAL:
            return result.error('Both runs must be finished', response_status=400)
        if request.query_params.get('routing'):
            from application.evaluation.routing import compare_routing
            routed = scoped_run(workspace_id, application_id, request.query_params['routing'])
            selected = {'low': left, 'high': right, 'routing': routed}
            if any(run.status != 'completed' or run.snapshot.get('routing_strategy') != role
                   for role, run in selected.items()):
                return result.error('Select completed low / high / routing runs in order', response_status=400)
            groups = {role: {**run_data(run, True), 'contract_hash': run.snapshot.get('config_hash')}
                      for role, run in selected.items()}
            return result.success(compare_routing(groups, {'quality_delta': 0, 'new_evidence_regressions': 0}))
        return result.success(compare_runs(run_data(left, True), run_data(right, True)))
