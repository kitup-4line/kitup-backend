import logging

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler, set_rollback

from core.responses import error

logger = logging.getLogger(__name__)


class ConflictError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "현재 상태에서 처리할 수 없는 요청입니다."
    default_code = "conflict"


class FrozenError(ConflictError):
    """리포트 생성(ended_at 기록) 이후 원가·고정비 수정 시도."""

    default_detail = "리포트가 생성된 테스트는 수정할 수 없습니다."
    default_code = "frozen"


class ImportNotReadyError(ConflictError):
    default_detail = "메뉴명, 판매가, 영업시간과 식재료비를 먼저 입력해주세요."
    default_code = "import_not_ready"


class AlreadyImportedError(ConflictError):
    default_detail = "이미 주문·리뷰 데이터를 불러온 테스트입니다."
    default_code = "already_imported"


class ReportAlreadyExistsError(ConflictError):
    default_detail = "이미 리포트가 생성되었습니다."
    default_code = "report_exists"


class RecommendationNotRetryableError(ConflictError):
    default_detail = "개선안 생성이 실패한 경우에만 다시 시도할 수 있습니다."
    default_code = "recommendation_not_retryable"


class NotDraftError(ConflictError):
    default_detail = "작성 중인 테스트만 삭제할 수 있습니다."
    default_code = "not_draft"


class BasicInfoRequiredError(ConflictError):
    default_detail = "메뉴명과 예상 판매가를 먼저 입력해주세요."
    default_code = "basic_info_required"


class CostNotReadyError(ConflictError):
    default_detail = "예상 판매가와 식재료비가 입력되어야 원가를 계산할 수 있습니다."
    default_code = "cost_not_ready"


class IngredientsChangedError(ConflictError):
    """AI 추정 중 테스트가 수정됨. 늦게 온 AI 결과로 덮어쓰지 않음."""

    default_detail = "AI 추정 중 테스트 정보가 변경되었습니다. 다시 시도해주세요."
    default_code = "ingredients_changed"


class AIServiceError(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "AI 응답을 처리하지 못했습니다."
    default_code = "ai_error"


def _first_message(detail):
    """중첩된 검증 오류에서 비어 있지 않은 첫 메시지를 찾음."""
    if isinstance(detail, dict):
        detail = list(detail.values())
    if isinstance(detail, list):
        for item in detail:
            message = _first_message(item)
            if message:
                return message
        return None
    return str(detail) if detail else None


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        set_rollback()
        logger.error("API 요청 처리 실패", exc_info=(type(exc), exc, exc.__traceback__))
        return error("server_error", "요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.", status=500)

    code = getattr(exc, "default_code", "error")
    detail = response.data
    if isinstance(detail, dict) and "detail" in detail:
        message = str(detail["detail"])
    else:
        # 검증 오류는 첫 번째 메시지를 message로 내려줌
        message = _first_message(detail) or "요청 값을 확인해주세요."
    response.data = {
        "success": False,
        "error": {"code": code, "message": message, "detail": detail},
    }
    return response
