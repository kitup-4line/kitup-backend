"""Swagger 문서용 공통 응답 형식."""

from drf_spectacular.utils import inline_serializer
from rest_framework import serializers


def envelope(name, data_serializer):
    return inline_serializer(
        name=name,
        fields={
            "success": serializers.BooleanField(),
            "message": serializers.CharField(allow_null=True),
            "data": data_serializer,
        },
    )
