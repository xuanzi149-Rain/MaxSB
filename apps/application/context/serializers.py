# coding=utf-8
"""Shared settings embedded in existing application/workflow JSON versions."""
from rest_framework import serializers
from application.context.processor import validate_config


class ContextPolicySerializer(serializers.Serializer):
    semantic_enabled = serializers.BooleanField(required=False)
    enabled = serializers.BooleanField(default=False)
    token_budget = serializers.IntegerField(default=2048, min_value=1, max_value=100000)
    similarity_threshold = serializers.FloatField(default=.95, min_value=.8, max_value=1)

    def validate(self, attrs):
        try:
            validate_config(attrs)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return attrs
