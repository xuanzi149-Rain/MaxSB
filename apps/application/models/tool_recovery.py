# coding=utf-8
"""Durable serial workflow checkpoints. Credentials are not stored here."""
import uuid
from django.db import models


class ToolRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey('application.Chat', on_delete=models.CASCADE)
    record_id = models.UUIDField(unique=True)
    snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=24, default='running')
    version = models.PositiveIntegerField(default=1)
    generation = models.PositiveIntegerField(default=1)
    resumes = models.PositiveIntegerField(default=0)
    requests = models.JSONField(default=dict)
    resolution = models.JSONField(default=list)
    failed_node = models.CharField(max_length=128, default='')
    lease_until = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'application_tool_run'


class ToolStep(models.Model):
    run = models.ForeignKey(ToolRun, on_delete=models.CASCADE, related_name='steps')
    node_id = models.CharField(max_length=128)
    node_type = models.CharField(max_length=64)
    status = models.CharField(max_length=24, default='pending')
    inputs = models.JSONField(default=dict)
    input_saved = models.BooleanField(default=False)
    policy = models.JSONField(default=dict)
    key = models.UUIDField(default=uuid.uuid4)
    output = models.JSONField(default=dict)
    variables = models.JSONField(default=dict)
    error_type = models.CharField(max_length=32, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'application_tool_step'
        constraints = [models.UniqueConstraint(fields=['run', 'node_id'], name='unique_recovery_node')]


class ToolAttempt(models.Model):
    step = models.ForeignKey(ToolStep, on_delete=models.CASCADE, related_name='attempts')
    generation = models.PositiveIntegerField()
    status = models.CharField(max_length=24, default='running')
    error_type = models.CharField(max_length=32, default='')
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True)
    wait_seconds = models.FloatField(default=0)

    class Meta:
        db_table = 'application_tool_attempt'
