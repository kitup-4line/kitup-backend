from rest_framework import serializers

from core.choices import AspectSentiment, Channel, RecommendationStatus, ReviewAnalysisStatus, Sentiment
from menu_tests.serializers import INT_MAX, OperatingPeriodSerializer, time_field

REVIEW_ASPECTS = ("taste", "portion", "temperature", "packaging")


# 금액은 원 단위 소수 4자리, 비율은 백분율(80.00 = 80%).
def money_field(**kwargs):
    return serializers.DecimalField(max_digits=24, decimal_places=4, **kwargs)


def percent_field(**kwargs):
    return serializers.DecimalField(max_digits=16, decimal_places=2, **kwargs)


class ChannelSummarySerializer(serializers.Serializer):
    order_type = serializers.ChoiceField(choices=Channel.choices)
    order_count = serializers.IntegerField()
    order_percentage = percent_field(allow_null=True)


class AnalysisDataSerializer(serializers.Serializer):
    completed_order_count = serializers.IntegerField()
    linked_review_count = serializers.IntegerField()
    channels = ChannelSummarySerializer(many=True)


class SalesConditionsSerializer(serializers.Serializer):
    selling_price = money_field(help_text="리포트 생성 당시의 메뉴 판매가")
    business_start_time = time_field()
    business_end_time = time_field()
    total_operating_hours = serializers.DecimalField(max_digits=12, decimal_places=2)
    orders_per_hour = serializers.DecimalField(
        max_digits=16, decimal_places=4, allow_null=True,
    )


class AnalysisConditionsSerializer(serializers.Serializer):
    operating_period = OperatingPeriodSerializer()
    kitchen_name = serializers.CharField()
    analysis_data = AnalysisDataSerializer()
    sales_conditions = SalesConditionsSerializer()


class ProfitSummarySerializer(serializers.Serializer):
    total_revenue = money_field(help_text="완료된 주문의 금액 합계")
    total_contribution_margin = money_field(help_text="총매출에서 변동비를 뺀 금액")
    contribution_margin_percentage = percent_field(allow_null=True)
    contribution_margin_per_order = money_field(allow_null=True)
    applied_fixed_cost = money_field(help_text="테스트 기간에 입력한 추가 고정비 전액")
    estimated_operating_profit = money_field(help_text="총 공헌이익에서 추가 고정비를 뺀 금액")
    operating_profit_percentage = percent_field(allow_null=True)


class CostComponentSerializer(serializers.Serializer):
    amount = money_field(allow_null=True)
    revenue_percentage = percent_field(allow_null=True)


class PerOrderStructureSerializer(serializers.Serializer):
    """완료 주문 1건당 평균 금액입니다. 고정비는 제외하며, 완료 주문이 없으면 금액은 null입니다."""

    average_revenue = money_field(allow_null=True)
    ingredient_cost = CostComponentSerializer()
    packaging_cost = CostComponentSerializer()
    delivery_fee = CostComponentSerializer()
    delivery_commission = CostComponentSerializer()
    contribution_margin = CostComponentSerializer()


class ProfitAnalysisSerializer(serializers.Serializer):
    summary = ProfitSummarySerializer()
    per_order_structure = PerOrderStructureSerializer()


class SalesTimeBucketSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="시간대를 구분하는 값")
    label = serializers.CharField(
        help_text=(
            "영업 시작부터 2시간씩 나눠 주문이 많은 구간을 최대 2개 표시합니다.  \n"
            "나머지는 기타로 묶습니다."
        ),
    )
    start_time = time_field(allow_null=True)
    end_time = time_field(allow_null=True)
    order_count = serializers.IntegerField()
    order_percentage = percent_field(allow_null=True)
    revenue = money_field()


class PeakSummarySerializer(serializers.Serializer):
    peak_order_count = serializers.IntegerField()
    peak_revenue = money_field()
    peak_revenue_percentage = percent_field(allow_null=True)


class SalesInsightsSerializer(serializers.Serializer):
    result = serializers.CharField()
    meaning = serializers.CharField()
    recommended_action = serializers.CharField(allow_null=True)
    limitation = serializers.CharField()


class SalesPatternSerializer(serializers.Serializer):
    time_buckets = SalesTimeBucketSerializer(many=True)
    peak_summary = PeakSummarySerializer()
    insights = SalesInsightsSerializer()


class QuantitativeReportSerializer(serializers.Serializer):
    """매출, 비용, 시간대별 판매를 계산한 결과."""

    analysis_conditions = AnalysisConditionsSerializer()
    profit_analysis = ProfitAnalysisSerializer()
    sales_pattern = SalesPatternSerializer()


class ReportCreateSerializer(serializers.Serializer):
    additional_fixed_cost = serializers.IntegerField(
        min_value=0, max_value=INT_MAX, required=False,
        help_text="최초 생성 시 필수인 추가 고정비(원). 비용이 없으면 0. 이후 요청은 저장된 값을 유지합니다.",
    )


class ReportAcceptedSerializer(serializers.Serializer):
    quantitative = QuantitativeReportSerializer()
    review_analysis_status = serializers.ChoiceField(
        choices=ReviewAnalysisStatus.choices,
        help_text="PENDING: 대기, RUNNING: 분석 중, SUCCEEDED: 완료, FAILED: 실패, NOT_REQUIRED: 리뷰 없음",
    )
    improvement_status = serializers.ChoiceField(
        choices=RecommendationStatus.choices,
        help_text="PENDING: 대기, RUNNING: 생성 중, SUCCEEDED: 완료, FAILED: 실패",
    )


class ReportQuerySerializer(serializers.Serializer):
    include_quantitative = serializers.BooleanField(
        default=True,
        help_text="기본값은 true입니다.  \nfalse이면 계산을 생략하고 quantitative를 반환하지 않습니다.",
    )


class ReviewLabelSerializer(serializers.Serializer):
    review_id = serializers.IntegerField()
    sentiment = serializers.ChoiceField(choices=Sentiment.choices)
    taste_sentiment = serializers.ChoiceField(choices=AspectSentiment.choices, allow_null=True)
    portion_sentiment = serializers.ChoiceField(choices=AspectSentiment.choices, allow_null=True)
    temperature_sentiment = serializers.ChoiceField(choices=AspectSentiment.choices, allow_null=True)
    packaging_sentiment = serializers.ChoiceField(choices=AspectSentiment.choices, allow_null=True)


class ReviewSentimentCountSerializer(serializers.Serializer):
    sentiment = serializers.ChoiceField(choices=["POSITIVE", "IMPROVEMENT_REQUIRED"])
    count = serializers.IntegerField()
    review_percentage = percent_field(allow_null=True)


class ReviewQuoteSerializer(serializers.Serializer):
    review_id = serializers.IntegerField(min_value=1)
    quote = serializers.CharField(max_length=160, trim_whitespace=False)


class EvidenceReviewQuerySerializer(serializers.Serializer):
    aspect = serializers.ChoiceField(choices=REVIEW_ASPECTS)
    sentiment = serializers.ChoiceField(choices=AspectSentiment.choices)


class ReviewQuoteCandidateSerializer(ReviewQuoteSerializer):
    aspect = serializers.ChoiceField(choices=REVIEW_ASPECTS)
    sentiment = serializers.ChoiceField(choices=AspectSentiment.choices)


class ReviewAspectCardSerializer(serializers.Serializer):
    aspect = serializers.ChoiceField(choices=REVIEW_ASPECTS)
    sentiment = serializers.ChoiceField(choices=AspectSentiment.choices)
    review_count = serializers.IntegerField()
    review_percentage = percent_field(
        allow_null=True,
        help_text="전체 리뷰 중 이 항목에 해당하는 비율입니다.  \n한 리뷰는 여러 항목에 포함될 수 있습니다.",
    )
    quotes = ReviewQuoteSerializer(many=True, help_text="리뷰 원문에서 뽑아 확인한 문구 최대 2개")


class ReviewAnalysisResultSerializer(serializers.Serializer):
    review_count = serializers.IntegerField()
    sentiments = ReviewSentimentCountSerializer(many=True)
    strengths = ReviewAspectCardSerializer(many=True, help_text="긍정 리뷰가 많은 항목 최대 2개")
    improvement_candidates = ReviewAspectCardSerializer(many=True, help_text="부정 리뷰가 많은 항목 최대 2개")


class ImprovementSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    action = serializers.CharField(max_length=3000)
    verification = serializers.CharField(max_length=1000)
    evidence_review_ids = serializers.ListField(child=serializers.IntegerField())


class ReportDetailSerializer(ReportAcceptedSerializer):
    quantitative = QuantitativeReportSerializer(required=False)
    review_analysis = ReviewAnalysisResultSerializer(
        allow_null=True, help_text="리뷰 분석이 SUCCEEDED일 때 반환합니다. 그 외에는 null입니다.",
    )
    improvements = ImprovementSerializer(
        many=True, allow_null=True, help_text="개선안 생성이 SUCCEEDED일 때 반환합니다. 그 외에는 null입니다.",
    )
