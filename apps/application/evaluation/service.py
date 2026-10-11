# coding=utf-8
import time
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from application.models import Application, EvaluationRun, EvaluationCaseResult
from application.evaluation.dataset import dataset_digest
from application.evaluation.metrics import summarize
from application.evaluation.scoring import score_case
from application.evaluation.sanitize import sanitize_result
from application.evaluation.snapshot import capture_snapshot
from application.evaluation.adapter import execute_case

TERMINAL = {'completed', 'configuration_drift', 'interrupted', 'dispatch_failed'}


def create_run(workspace_id: str, application_id: str, user_id: str, dataset: dict, enqueue=True, routing_strategy=None) -> EvaluationRun:
    Application.objects.get(pk=application_id, workspace_id=workspace_id)
    snapshot = capture_snapshot(application_id)
    if routing_strategy is not None:
        if routing_strategy not in {'low', 'high', 'routing'}:
            raise ValueError('invalid_routing_strategy')
        nodes = snapshot.get('application_config', {}).get('work_flow', {}).get('nodes', [])
        if not any((n.get('properties', {}).get('node_data', {}).get('model_routing') or {}).get('enabled')
                   for n in nodes):
            raise ValueError('routing_evaluation_requires_enabled_node')
        snapshot['routing_strategy'] = routing_strategy
    snapshot['user_id'] = user_id
    with transaction.atomic():
        run = EvaluationRun.objects.create(application_id=application_id, workspace_id=workspace_id, user_id=user_id,
                                            dataset=dataset, dataset_hash=dataset_digest(dataset), snapshot=snapshot)
        def dispatch():
            from application.tasks import run_evaluation
            try:
                run_evaluation.delay(str(run.pk))
            except Exception:
                EvaluationRun.objects.filter(pk=run.pk, status='queued').update(
                    status='dispatch_failed', error='broker_unavailable', finished_at=timezone.now())
        if enqueue:
            transaction.on_commit(dispatch)
    return run


def reconcile_interrupted():
    # A case is bounded to 180 s. A stale heartbeat is never retried automatically.
    EvaluationRun.objects.filter(status='running', heartbeat_at__lt=timezone.now() - timedelta(minutes=5)).update(
        status='interrupted', error='worker_heartbeat_expired', finished_at=timezone.now())


def execute_run(run_id: str) -> None:
    claimed = EvaluationRun.objects.filter(pk=run_id, status='queued').update(
        status='running', started_at=timezone.now(), heartbeat_at=timezone.now())
    if not claimed:
        return
    run = EvaluationRun.objects.get(pk=run_id)
    final_status = 'completed'
    try:
        for case in run.dataset['cases']:
            if capture_snapshot(str(run.application_id))['config_hash'] != run.snapshot['config_hash']:
                final_status = 'configuration_drift'
                break
            started = time.monotonic()
            try:
                result = sanitize_result(execute_case(case, run.snapshot))
            except Exception as exc:
                result = {'answer': '', 'status': 'failed', 'error': type(exc).__name__,
                          'input_tokens': None, 'output_tokens': None, 'actual_cost': None}
            result.update(case_id=case['case_id'], scenario=case['scenario'], elapsed_seconds=time.monotonic() - started)
            drifted = result.get('error') == 'configuration_drift' or capture_snapshot(str(run.application_id))['config_hash'] != run.snapshot['config_hash']
            if drifted:
                result.update(status='failed', error='configuration_drift')
            result['score'] = score_case(case, result)
            EvaluationCaseResult.objects.create(run=run, case_id=case['case_id'], status=result['status'], result=result)
            EvaluationRun.objects.filter(pk=run_id).update(heartbeat_at=timezone.now())
            if drifted:
                final_status = 'configuration_drift'
                break
    except Exception as exc:
        final_status = 'interrupted'
        run.error = type(exc).__name__
    rows = [item.result for item in run.results.all()]
    run.status, run.finished_at, run.summary = final_status, timezone.now(), summarize(rows, total_cases=len(run.dataset['cases']))
    run.save(update_fields=['status', 'finished_at', 'summary', 'error', 'update_time'])
