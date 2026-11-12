"""정량 결과와 리뷰를 근거로 개선안을 생성한다."""

from collections.abc import Mapping

from core.exceptions import AIServiceError
from reports import providers
from reports.serializers import ImprovementSerializer, QuantitativeReportSerializer


def generate(
    quantitative: dict, reviews: list[dict], *, generator: providers.ImprovementGenerator | None = None,
) -> providers.ImprovementResult:
    if generator is None:
        generator = providers.get_improvement_generator()
    payload = generator.generate(QuantitativeReportSerializer(quantitative).data, reviews)
    if not isinstance(payload, Mapping):
        raise AIServiceError("개선안 응답 형식이 올바르지 않습니다.")
    serializer = ImprovementSerializer(data=payload.get("items"), many=True)
    if not serializer.is_valid() or not 1 <= len(serializer.validated_data) <= 4:
        raise AIServiceError("개선안 응답 형식이 올바르지 않습니다.")
    valid_ids = {row["review_id"] for row in reviews}
    for item in serializer.validated_data:
        ids = item["evidence_review_ids"]
        if len(ids) != len(set(ids)) or not set(ids) <= valid_ids:
            raise AIServiceError("개선안의 근거 리뷰가 올바르지 않습니다.")
    return {"items": serializer.validated_data}
