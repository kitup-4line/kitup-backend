from django.db.models import F
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.views import APIView

from core.choices import ReviewAnalysisStatus
from core.exceptions import ReviewAnalysisNotReadyError
from core.responses import success
from core.schema import envelope
from menu_tests.services.menu_test_service import get_test_or_404
from orders.models import Review
from orders.serializers import OrderReviewSerializer

from .examples import EVIDENCE_REVIEW_EXAMPLES, REPORT_CREATE_EXAMPLES, REPORT_DETAIL_EXAMPLES
from .serializers import (
    EvidenceReviewQuerySerializer,
    ReportAcceptedSerializer,
    ReportCreateSerializer,
    ReportDetailSerializer,
    ReportQuerySerializer,
)
from .services import report_builder


class ReportView(APIView):
    """리포트 생성 요청과 조회."""

    @extend_schema(
        tags=["reports"],
        summary="리포트 생성 또는 재시도",
        description=(
            "추가 고정비를 저장하고 리포트 생성을 시작합니다.  \n"
            "계산 결과는 바로 반환하고, AI 분석은 이후 진행합니다.  \n"
            "실패 후 같은 POST를 보내면 실패한 단계부터 다시 시작합니다.  \n"
            "추가 고정비는 처음에만 필수입니다. 이후에는 저장된 고정비와 완료된 리뷰 분석 결과를 유지합니다.  \n"
            "진행 중이거나 완료된 경우 새 작업 없이 현재 상태와 계산 결과를 반환합니다.\n\n"
            "**호출 순서**\n\n"
            "생성 POST → 계산 결과 표시 → 리포트 GET으로 상태 확인  \n"
            "반복 조회에는 `include_quantitative=false`를 사용합니다.  \n"
            "요청 오류나 통신 오류가 나면 로딩과 반복 조회를 중단하고 오류를 표시합니다. 자동으로 다시 요청하지 않습니다."
        ),
        request=ReportCreateSerializer,
        responses={
            202: OpenApiResponse(
                response=envelope("ReportAcceptedResponse", ReportAcceptedSerializer()),
                description="현재 상태와 계산 결과를 반환합니다. AI 결과는 리포트 GET으로 확인합니다.",
                examples=REPORT_CREATE_EXAMPLES,
            ),
            400: OpenApiResponse(description="추가 고정비 값이 올바르지 않습니다."),
            404: OpenApiResponse(description="테스트를 찾을 수 없습니다."),
            409: OpenApiResponse(description="주문이나 원가가 준비되지 않았습니다."),
            500: OpenApiResponse(description="요청 처리에 실패했습니다. 로딩을 종료하고 오류를 표시합니다."),
        },
    )
    def post(self, request, test_id):
        serializer = ReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = report_builder.start_report(test_id, **serializer.validated_data)
        return success(
            ReportAcceptedSerializer(result).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        tags=["reports"],
        summary="리포트 조회",
        description=(
            "리포트 결과와 AI 진행 상태를 조회합니다. AI를 다시 호출하지 않습니다.\n\n"
            "**상태별 처리**\n\n"
            "리뷰: `review_analysis_status`, 개선안: `improvement_status`\n\n"
            "| 리뷰 | 개선안 | 화면 표시 | 자동 조회 |\n|---|---|---|---|\n"
            "| PENDING / RUNNING | PENDING | 리뷰 분석 대기 / 진행 중 | 계속 |\n"
            "| SUCCEEDED / NOT_REQUIRED | PENDING / RUNNING | 개선안 대기 / 생성 중 | 계속 |\n"
            "| FAILED | PENDING | 리뷰 분석 실패 | 중단 |\n"
            "| SUCCEEDED / NOT_REQUIRED | FAILED | 개선안 생성 실패, 완료된 리뷰 결과 유지 | 중단 |\n"
            "| SUCCEEDED / NOT_REQUIRED | SUCCEEDED | 전체 완료 | 중단 |\n\n"
            "`NOT_REQUIRED`는 리뷰가 없어 분석을 생략한 상태입니다.  \n"
            "요청 오류나 통신 오류가 나면 로딩과 반복 조회를 중단하고 오류를 표시합니다.  \n"
            "아래 200 응답에서 상태별 JSON 예시를 선택할 수 있습니다."
        ),
        parameters=[ReportQuerySerializer],
        responses={
            200: OpenApiResponse(
                response=envelope("ReportStatusResponse", ReportDetailSerializer()),
                description="조회 성공. AI 성공 여부는 상태 필드로 확인합니다.",
                examples=REPORT_DETAIL_EXAMPLES,
            ),
            400: OpenApiResponse(description="조회 옵션 값이 올바르지 않습니다."),
            404: OpenApiResponse(description="테스트 또는 접수된 리포트가 없습니다."),
            500: OpenApiResponse(description="조회에 실패했습니다. 로딩과 반복 조회를 중단하고 오류를 표시합니다."),
        },
    )
    def get(self, request, test_id):
        serializer = ReportQuerySerializer(data=request.query_params.dict())
        serializer.is_valid(raise_exception=True)
        result = report_builder.get_report(test_id, **serializer.validated_data)
        response = success(ReportDetailSerializer(result).data)
        response["Cache-Control"] = "no-store"
        return response


class CategoryReviewsView(APIView):
    """분석에 사용한 리뷰 원문 조회."""

    @extend_schema(
        tags=["reports"], summary="근거 리뷰 조회",
        description=(
            "선택한 분석 항목에 해당하는 리뷰 원문을 조회합니다.  \n"
            "리뷰 분석이 완료되면 개선안 상태와 관계없이 조회할 수 있습니다."
        ),
        parameters=[EvidenceReviewQuerySerializer],
        responses={
            200: OpenApiResponse(
                response=envelope("ReportEvidenceReviewsResponse", OrderReviewSerializer(many=True)),
                description=(
                    "최신순입니다. 작성 시각이 없는 리뷰는 마지막에 표시합니다.  \n"
                    "리뷰가 없거나 조건에 맞는 리뷰가 없으면 data는 빈 목록입니다."
                ),
                examples=EVIDENCE_REVIEW_EXAMPLES,
            ),
            400: OpenApiResponse(description="분석 항목이나 감정 값이 빠졌거나 올바르지 않습니다."),
            404: OpenApiResponse(description="테스트가 없거나 리포트 생성을 요청하지 않았습니다."),
            409: OpenApiResponse(description="리뷰 분석이 아직 끝나지 않았거나 실패했습니다."),
            500: OpenApiResponse(description="리뷰를 불러오지 못했습니다."),
        },
    )
    def get(self, request, test_id):
        serializer = EvidenceReviewQuerySerializer(data=request.query_params.dict())
        serializer.is_valid(raise_exception=True)
        test = get_test_or_404(test_id)
        if test.ended_at is None:
            raise NotFound("생성 요청한 리포트가 없습니다.")
        if test.review_analysis_status not in (
            ReviewAnalysisStatus.SUCCEEDED, ReviewAnalysisStatus.NOT_REQUIRED,
        ):
            raise ReviewAnalysisNotReadyError()
        reviews = Review.objects.none()
        if test.review_analysis_status == ReviewAnalysisStatus.SUCCEEDED:
            filters = serializer.validated_data
            reviews = Review.objects.filter(
                order__test_id=test_id,
                **{f"{filters['aspect']}_sentiment": filters["sentiment"]},
            ).order_by(F("written_at").desc(nulls_last=True), "-id")
        response = success(OrderReviewSerializer(reviews, many=True).data)
        response["Cache-Control"] = "no-store"
        return response
