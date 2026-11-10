from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.views import APIView

from core.responses import success
from menu_tests.services.menu_test_service import get_test_or_404

from .models import Order
from .serializers import OrderImportResultSerializer, OrderListSerializer
from .services import import_service


class OrderListView(APIView):
    """GET 주문·리뷰 목록"""

    @extend_schema(
        tags=["orders"],
        summary="주문·리뷰 목록 조회",
        description="주문 시각·ID 오름차순으로 전체 목록을 반환합니다. "
                    "리뷰 원문을 함께 제공하며 리뷰가 없는 주문은 review가 null입니다. "
                    "페이지 구분은 프론트에서 처리합니다.",
        responses={
            200: inline_serializer(name="OrderListResponse", fields={
                "success": serializers.BooleanField(),
                "message": serializers.CharField(allow_null=True),
                "data": OrderListSerializer(many=True),
            }),
            404: OpenApiResponse(description="not_found"),
            500: OpenApiResponse(description="server_error: 조회 실패"),
        },
    )
    def get(self, request, test_id):
        get_test_or_404(test_id)
        orders = (
            Order.objects.filter(test_id=test_id)
            .select_related("review")
            .order_by("created_at", "id")
        )
        return success(OrderListSerializer(orders, many=True).data)


class OrderImportSampleView(APIView):
    """POST 가상 주문·리뷰 불러오기와 운영 시작."""

    @extend_schema(
        tags=["orders"],
        summary="가상 주문, 리뷰 불러오기",
        description="요청 본문은 사용하지 않습니다. 불러오기 성공 시 운영을 시작합니다. "
                    "등록일까지의 과거 14일로 샘플을 옮기고 공유주방·기간을 함께 보존합니다.",
        request=None,
        responses={
            201: inline_serializer(name="OrderImportResponse", fields={
                "success": serializers.BooleanField(),
                "message": serializers.CharField(allow_null=True),
                "data": OrderImportResultSerializer(),
            }),
            404: OpenApiResponse(description="not_found"),
            409: OpenApiResponse(description="already_imported / frozen / import_not_ready"),
            500: OpenApiResponse(description="server_error: 전체 저장 취소"),
        },
    )
    def post(self, request, test_id):
        result = import_service.import_sample(test_id)
        return success(
            OrderImportResultSerializer(result).data,
            status=status.HTTP_201_CREATED,
        )
