# coding=utf-8
"""Durable evaluation runs, independent of chat-history retention."""
import uuid
from django.db import models
from common.mixins.app_model_mixin import AppModelMixin


class EvaluationRun(AppModelMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey('application.Application', on_delete=models.CASCADE)
    workspace_id = models.CharField(max_length=64, db_index=True)
    user_id = models.CharField(max_length=64)
    status = models.CharField(max_length=32, default='queued', db_index=True)
    dataset = models.JSONField(default=dict)
    dataset_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    summary = models.JSONField(default=dict)
    error = models.CharField(max_length=128, default='')
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    heartbeat_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'application_evaluation_run'


class EvaluationCaseResult(AppModelMixin):
    run = models.ForeignKey(EvaluationRun, on_delete=models.CASCADE, related_name='results')
    case_id = models.CharField(max_length=128)
    status = models.CharField(max_length=32)
    result = models.JSONField(default=dict)
    review = models.JSONField(default=dict)
    review_history = models.JSONField(default=list)

    class Meta:
        db_table = 'application_evaluation_case'
        constraints = [models.UniqueConstraint(fields=('run', 'case_id'), name='evaluation_run_case_unique')]
