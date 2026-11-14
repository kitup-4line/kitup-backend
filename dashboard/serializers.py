from rest_framework import serializers

from core.choices import Channel

# 금액은 원 단위 정수, 비중은 % (소수 1자리)


def _ratio_field():
    return serializers.DecimalField(max_digits=5, decimal_places=1, allow_null=True)


class SummarySerializer(serializers.Serializer):
    completed_order_count = serializers.IntegerField()
    completed_sales_amount = serializers.IntegerField()
    total_contribution_margin = serializers.IntegerField()
    average_contribution_margin = serializers.IntegerField(allow_null=True)
    fixed_cost_applied = serializers.BooleanField()


class _HourSlotSerializer(serializers.Serializer):
    hour = serializers.IntegerField()
    label = serializers.SerializerMethodField()
    order_count = serializers.IntegerField()
    ratio = _ratio_field()
    is_peak = serializers.BooleanField()

    def get_label(self, obj) -> str:
        return f"{obj['hour']:02d}:00 - {obj['hour'] + 1:02d}:00"


class _PeakSerializer(serializers.Serializer):
    hours = serializers.ListField(child=serializers.IntegerField())
    order_count = serializers.IntegerField()
    ratio = _ratio_field()


class HourlySalesSerializer(serializers.Serializer):
    total_order_count = serializers.IntegerField()
    peak = _PeakSerializer(allow_null=True)
    slots = _HourSlotSerializer(many=True)


class _ChannelSerializer(serializers.Serializer):
    order_type = serializers.ChoiceField(choices=Channel.choices)
    order_count = serializers.IntegerField()
    contribution_margin_per_order = serializers.IntegerField(
        source="average_contribution_margin", allow_null=True
    )
    total_contribution_margin = serializers.IntegerField()


class ChannelComparisonSerializer(serializers.Serializer):
    channels = _ChannelSerializer(many=True)
