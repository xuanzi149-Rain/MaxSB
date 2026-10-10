# coding=utf-8
from rest_framework import serializers


class MemoryMutationSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=0)
    request_id = serializers.UUIDField()
    operation = serializers.ChoiceField(choices=['replace', 'confirm', 'revoke'], required=False)
    value = serializers.CharField(max_length=2048, required=False, allow_blank=True)
