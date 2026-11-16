from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.views import APIView

from core.responses import success
from core.schema import envelope
from menu_tests.services.menu_test_service import get_test_or_404

from .serializers import ChannelComparisonSerializer, HourlySalesSerializer, SummarySerializer
from .services import metrics

TAGS = ["dashboard"]
NOT_FOUND = OpenApiResponse(description="not_found")


class DashboardSummaryView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="핵심 지표 카드 조회",
        description="완료 주문, 완료 매출, 추정 총공헌이익, 평균 건당 공헌이익. "
                    "추가 고정비는 차감하지 않음(fixed_cost_applied=false). 주문이 없으면 0, 평균은 null.",
        responses={200: envelope("DashboardSummaryResponse", SummarySerializer()), 404: NOT_FOUND},
    )
    def get(self, request, test_id):
        test = get_test_or_404(test_id)
        return success(SummarySerializer(metrics.summary(test)).data)


class HourlySalesView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="시간대별 판매 조회",
        description="1시간 단위(한국 시간) 주문 건수와 비중, 상위 5개 시간대. 건수 내림차순, 같으면 시각 오름차순. "
                    "peak는 주문이 많은 상위 2개 시간대의 합계(하단 안내 문구용).",
        responses={200: envelope("HourlySalesResponse", HourlySalesSerializer()), 404: NOT_FOUND},
    )
    def get(self, request, test_id):
        test = get_test_or_404(test_id)
        return success(HourlySalesSerializer(metrics.hourly_sales(test)).data)


class ChannelComparisonView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="배달·픽업 비교 조회",
        description="유형별 완료 주문, 건당 공헌이익, 총공헌이익. 0건인 채널도 포함(건당 공헌이익 null).",
        responses={200: envelope("ChannelComparisonResponse", ChannelComparisonSerializer()), 404: NOT_FOUND},
    )
    def get(self, request, test_id):
        test = get_test_or_404(test_id)
        return success(ChannelComparisonSerializer(metrics.channels(test)).data)
