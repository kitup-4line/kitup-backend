from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.choices import IngredientUnit
from core.constants import (
    DEFAULT_PACKAGING_COST,
    DELIVERY_COMMISSION_RATE,
    DELIVERY_FEE,
    OPERATING_HOUR_CHOICES,
)
from core.responses import success

from .models import MenuTest
from .serializers import (
    AIEstimateInputSerializer,
    CostSummarySerializer,
    IngredientBulkInputSerializer,
    IngredientListSerializer,
    MenuTestDetailSerializer,
    MenuTestListSerializer,
    MenuTestUpdateSerializer,
    TestDefaultsSerializer,
)
from .services import ai_estimate_service, cost_service, menu_test_service

TAGS = ["menu_tests"]


def envelope(name, data_serializer):
    """문서용 공통 응답 형식."""
    return inline_serializer(
        name=name,
        fields={
            "success": serializers.BooleanField(),
            "message": serializers.CharField(allow_null=True),
            "data": data_serializer,
        },
    )


def error(description):
    return OpenApiResponse(description=description)


def ingredient_list_data(test: MenuTest) -> dict:
    return IngredientListSerializer(
        {
            "total_ingredient_cost": test.total_ingredient_cost,
            "ingredients": test.ingredients.order_by("id"),
        }
    ).data


class MenuTestListCreateView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="테스트 목록 조회",
        operation_id="tests_list",
        responses={200: envelope("MenuTestListResponse", MenuTestListSerializer(many=True))},
    )
    def get(self, request):
        tests = MenuTest.objects.order_by("-created_at", "-id")
        return success(MenuTestListSerializer(tests, many=True).data)

    @extend_schema(
        tags=TAGS,
        summary="테스트 생성 (빈 초안)",
        request=None,
        responses={201: envelope("MenuTestCreateResponse", MenuTestDetailSerializer())},
    )
    def post(self, request):
        test = MenuTest.objects.create()
        return success(MenuTestDetailSerializer(test).data, status=status.HTTP_201_CREATED)


class TestDefaultsView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="입력 초깃값 조회",
        responses={200: envelope("TestDefaultsResponse", TestDefaultsSerializer())},
    )
    def get(self, request):
        data = {
            "packaging_cost": DEFAULT_PACKAGING_COST,
            "delivery_fee": DELIVERY_FEE,
            "delivery_commission_rate": DELIVERY_COMMISSION_RATE,
            "business_hour_options": OPERATING_HOUR_CHOICES,
            "ingredient_unit_options": [
                {"value": value, "label": label} for value, label in IngredientUnit.choices
            ],
        }
        return success(TestDefaultsSerializer(data).data)


class MenuTestDetailView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="테스트 상세 조회",
        responses={
            200: envelope("MenuTestDetailResponse", MenuTestDetailSerializer()),
            404: error("not_found"),
        },
    )
    def get(self, request, test_id):
        test = menu_test_service.get_test_or_404(test_id)
        return success(MenuTestDetailSerializer(test).data)

    @extend_schema(
        tags=TAGS,
        summary="기본 정보·추가 고정비 수정",
        request=MenuTestUpdateSerializer,
        responses={
            200: envelope("MenuTestUpdateResponse", MenuTestDetailSerializer()),
            400: error("입력값 검증 실패"),
            404: error("not_found"),
            409: error("frozen: 리포트 생성 후 수정 불가"),
        },
    )
    def patch(self, request, test_id):
        test = menu_test_service.get_test_or_404(test_id)
        menu_test_service.assert_editable(test)
        serializer = MenuTestUpdateSerializer(instance=test, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        test = menu_test_service.update_test(test, serializer.validated_data)
        return success(MenuTestDetailSerializer(test).data)

    # TODO(팀 확인): 초안 삭제 API는 합의 대기 중. 빼기로 하면 이 메서드만 삭제
    @extend_schema(
        tags=TAGS,
        summary="초안 삭제",
        responses={
            204: None,
            404: error("not_found"),
            409: error("not_draft: 작성 중인 테스트만 삭제 가능"),
        },
    )
    def delete(self, request, test_id):
        test = menu_test_service.get_test_or_404(test_id)
        menu_test_service.delete_draft(test)
        return Response(status=status.HTTP_204_NO_CONTENT)


class IngredientView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="재료 목록 조회",
        responses={
            200: envelope("IngredientListResponse", IngredientListSerializer()),
            404: error("not_found"),
        },
    )
    def get(self, request, test_id):
        test = menu_test_service.get_test_or_404(test_id)
        return success(ingredient_list_data(test))

    @extend_schema(
        tags=TAGS,
        summary="재료 일괄 저장 (전체 교체)",
        request=IngredientBulkInputSerializer,
        responses={
            200: envelope("IngredientSaveResponse", IngredientListSerializer()),
            400: error("입력값 검증 실패"),
            404: error("not_found"),
            409: error("frozen: 리포트 생성 후 수정 불가"),
        },
    )
    def put(self, request, test_id):
        test = menu_test_service.get_test_or_404(test_id)
        menu_test_service.assert_editable(test)
        serializer = IngredientBulkInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        test = cost_service.replace_ingredients(test, serializer.validated_data["ingredients"])
        return success(ingredient_list_data(test))


class IngredientAIEstimateView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="AI 재료 원가 추정",
        request=AIEstimateInputSerializer,
        responses={
            200: envelope("IngredientEstimateResponse", IngredientListSerializer()),
            400: error("입력값 검증 실패"),
            404: error("not_found"),
            409: error("frozen / basic_info_required"),
            502: error("ai_error: AI 호출·응답 검증 실패, DB 변경 없음"),
        },
    )
    def post(self, request, test_id):
        test = menu_test_service.get_test_or_404(test_id)
        ai_estimate_service.assert_ready_for_estimate(test)
        serializer = AIEstimateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        test = ai_estimate_service.estimate_and_save(
            test, serializer.validated_data["ingredient_names"]
        )
        return success(ingredient_list_data(test))


class CostView(APIView):
    @extend_schema(
        tags=TAGS,
        summary="원가 산정 결과 조회",
        responses={
            200: envelope("CostSummaryResponse", CostSummarySerializer()),
            404: error("not_found"),
            409: error("cost_not_ready: 판매가 또는 식재료비 없음"),
        },
    )
    def get(self, request, test_id):
        test = menu_test_service.get_test_or_404(test_id)
        return success(CostSummarySerializer(cost_service.build_cost_summary(test)).data)
