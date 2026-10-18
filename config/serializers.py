from rest_framework import serializers


class HealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok", "degraded"])
    database = serializers.BooleanField()
    redis = serializers.BooleanField()
