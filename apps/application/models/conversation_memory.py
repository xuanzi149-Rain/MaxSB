# coding=utf-8
"""Session-scoped memory with immutable source events and optimistic versions."""
import uuid
from django.db import models


class ConversationMemory(models.Model):
    chat = models.OneToOneField('application.Chat', on_delete=models.CASCADE, primary_key=True)
    version = models.PositiveIntegerField(default=0)
    generation = models.PositiveIntegerField(default=0)
    facts = models.JSONField(default=list)
    history_since = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'application_conversation_memory'


class ConversationMemoryEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    memory = models.ForeignKey(ConversationMemory, on_delete=models.CASCADE, related_name='events')
    generation = models.PositiveIntegerField(default=0)
    request_id = models.CharField(max_length=128)
    record_id = models.CharField(max_length=36, blank=True)
    question = models.TextField(default='')
    question_hash = models.CharField(max_length=64, default='')
    kind = models.CharField(max_length=24, default='turn')
    status = models.CharField(max_length=24, default='received')
    base_version = models.PositiveIntegerField(default=0)
    result_version = models.PositiveIntegerField(default=0)
    changes = models.JSONField(default=list)
    usage = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'application_conversation_memory_event'
        constraints = [models.UniqueConstraint(fields=['memory', 'generation', 'request_id'],
                                               name='unique_memory_request')]
