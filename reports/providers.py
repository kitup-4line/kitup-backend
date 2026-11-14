"""분석 구현의 입력·출력 계약과 선택. 검증·집계·저장은 서비스가 담당한다."""

from collections.abc import Mapping
from typing import Protocol, TypedDict

from rest_framework.renderers import JSONRenderer

from ai.prompts import recommendation, review_analysis

from . import ai_client


class ReviewAnalysisResult(TypedDict):
    """서비스 검증을 통과한 리뷰 분석 결과."""

    reviews: list[dict]
    quotes: list[dict]


class ImprovementResult(TypedDict):
    """서비스 검증을 통과한 개선안 결과."""

    items: list[dict]


class ReviewAnalyzer(Protocol):
    def analyze(self, reviews: list[dict]) -> Mapping[str, object]:
        """reviews·quotes 후보를 반환한다. 값의 유효성은 서비스에서 검증한다."""
        ...


class ImprovementGenerator(Protocol):
    def generate(self, quantitative: dict, reviews: list[dict]) -> Mapping[str, object]:
        """API 응답 정밀도의 정량 결과로 items 후보를 반환한다. 출력 검증은 서비스가 담당한다."""
        ...


class APIReviewAnalyzer:
    def analyze(self, reviews: list[dict]) -> dict[str, object]:
        user = JSONRenderer().render(reviews).decode()
        return ai_client.request_json(
            "REVIEW", review_analysis.SYSTEM_PROMPT, user, max_tokens=12288,
        )


class APIImprovementGenerator:
    def generate(self, quantitative: dict, reviews: list[dict]) -> dict[str, object]:
        user = JSONRenderer().render({"quantitative": quantitative, "reviews": reviews}).decode()
        return ai_client.request_json(
            "IMPROVEMENT", recommendation.SYSTEM_PROMPT, user, max_tokens=4096,
        )


def get_review_analyzer() -> ReviewAnalyzer:
    return APIReviewAnalyzer()


def get_improvement_generator() -> ImprovementGenerator:
    return APIImprovementGenerator()
