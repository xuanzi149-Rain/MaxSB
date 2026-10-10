# coding=utf-8
"""Optional workflow settings; existing workflows require no migration."""
from rest_framework import serializers


class RetrievalProfileSerializer(serializers.Serializer):
    retrieve = serializers.BooleanField(required=True)
    top_n = serializers.IntegerField(required=True, min_value=1, max_value=10000)
    rerank = serializers.BooleanField(required=True)


class RetrievalPolicySerializer(serializers.Serializer):
    enabled = serializers.BooleanField(default=False)
    none = RetrievalProfileSerializer(required=False)
    simple = RetrievalProfileSerializer(required=False)
    complex = RetrievalProfileSerializer(required=False)
