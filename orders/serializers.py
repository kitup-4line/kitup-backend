from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from core.choices import Channel, TestStatus

from .models import Order, Review


class _OrderReviewSerializer(serializers.ModelSerializer):
    review_id = serializers.IntegerField(source="id", read_only=True)

    class Meta:
        model = Review
        fields = ["review_id", "content", "written_at"]
        read_only_fields = fields


class OrderListSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source="id", read_only=True)
    review = _OrderReviewSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Order
        fields = ["order_id", "created_at", "order_type", "sales_amount", "review"]
        read_only_fields = fields


class SamplePeriodSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    operating_days = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        days = (attrs["end_date"] - attrs["start_date"]).days + 1
        if days < 1 or days != attrs["operating_days"]:
            raise serializers.ValidationError("샘플 시작일, 종료일과 운영 일수가 일치하지 않습니다.")
        return attrs


class OrderImportResultSerializer(serializers.Serializer):
    test_id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=TestStatus.choices)
    started_at = serializers.DateTimeField()
    kitchen_name = serializers.CharField()
    period = SamplePeriodSerializer()
    order_count = serializers.IntegerField()
    review_count = serializers.IntegerField()


class _SampleDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, value):
        try:
            parsed = parse_datetime(value) if isinstance(value, str) else None
        except ValueError:
            parsed = None
        if parsed is None or timezone.is_naive(parsed):
            raise serializers.ValidationError("시간대가 포함된 시각이 필요합니다.")
        return super().to_internal_value(value)


class _SampleOrderSerializer(serializers.Serializer):
    sample_order_id = serializers.IntegerField(min_value=1)
    order_type = serializers.ChoiceField(choices=Channel.choices)
    created_at = _SampleDateTimeField()


class _SampleReviewSerializer(serializers.Serializer):
    sample_review_id = serializers.IntegerField(min_value=1)
    sample_order_id = serializers.IntegerField(min_value=1)
    content = serializers.CharField(trim_whitespace=False)
    written_at = _SampleDateTimeField()

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError("리뷰 원문이 비어 있습니다.")
        return value


class SamplePackageSerializer(serializers.Serializer):
    """서버 샘플 검증용. 외부 요청 본문으로 받지 않는다."""

    kitchen_name = serializers.CharField(max_length=100)
    period = SamplePeriodSerializer()
    orders = _SampleOrderSerializer(many=True, min_length=60, max_length=60)
    reviews = _SampleReviewSerializer(many=True, min_length=48, max_length=48)

    def validate(self, attrs):
        orders = {item["sample_order_id"]: item for item in attrs["orders"]}
        reviews = attrs["reviews"]
        if len(orders) != len(attrs["orders"]):
            raise serializers.ValidationError("중복된 샘플 주문 ID입니다.")
        for order in orders.values():
            ordered_on = timezone.localtime(order["created_at"]).date()
            if not attrs["period"]["start_date"] <= ordered_on <= attrs["period"]["end_date"]:
                raise serializers.ValidationError("주문 시각이 샘플 운영 기간을 벗어났습니다.")
        for field in ("sample_review_id", "sample_order_id"):
            if len({item[field] for item in reviews}) != len(reviews):
                raise serializers.ValidationError("중복된 샘플 리뷰 연결입니다.")
        for review in reviews:
            order = orders.get(review["sample_order_id"])
            if order is None or review["written_at"] < order["created_at"]:
                raise serializers.ValidationError("리뷰의 주문 연결 또는 작성 시각이 올바르지 않습니다.")
        return attrs
