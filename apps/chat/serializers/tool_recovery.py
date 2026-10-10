# coding=utf-8
from rest_framework import serializers


class ResumeSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    expected_version = serializers.IntegerField(min_value=1)

    def to_internal_value(self, data):
        if set(data) - set(self.fields):
            raise serializers.ValidationError('Unsupported recovery fields')
        return super().to_internal_value(data)


class ResolutionSerializer(ResumeSerializer):
    conclusion = serializers.ChoiceField(choices=['executed', 'not_executed'])
    evidence = serializers.CharField(min_length=10, max_length=2048)
    output = serializers.ListField(child=serializers.CharField(allow_blank=True), required=False)
