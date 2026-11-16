from django.db import models


class TestStatus(models.TextChoices):
    """저장하지 않음. started_at / ended_at으로 계산."""

    DRAFT = "DRAFT", "작성 중"
    RUNNING = "RUNNING", "운영 중"
    COMPLETED = "COMPLETED", "종료"


class CostMethod(models.TextChoices):
    MANUAL = "MANUAL", "직접 입력"
    AI = "AI", "AI 추정"


class CostSource(models.TextChoices):
    ESTIMATED = "ESTIMATED", "추정 원가"
    MEASURED = "MEASURED", "실측 원가"


class Channel(models.TextChoices):
    DELIVERY = "DELIVERY", "배달"
    PICKUP = "PICKUP", "픽업"


class OrderStatus(models.TextChoices):
    COMPLETED = "COMPLETED", "완료"
    CANCELED = "CANCELED", "취소"


class RecommendationStatus(models.TextChoices):
    """FAILED일 때만 retry 허용."""

    PENDING = "PENDING", "대기"
    RUNNING = "RUNNING", "생성 중"
    SUCCEEDED = "SUCCEEDED", "생성 완료"
    FAILED = "FAILED", "생성 실패"


class ReviewAnalysisStatus(models.TextChoices):
    PENDING = "PENDING", "대기"
    RUNNING = "RUNNING", "분석 중"
    SUCCEEDED = "SUCCEEDED", "분석 완료"
    FAILED = "FAILED", "분석 실패"
    NOT_REQUIRED = "NOT_REQUIRED", "리뷰 없음"


class IngredientUnit(models.TextChoices):
    GRAM = "g", "그램"
    KILOGRAM = "kg", "킬로그램"
    MILLILITER = "ml", "밀리리터"
    LITER = "l", "리터"
    PIECE = "piece", "개"


class Sentiment(models.TextChoices):
    POSITIVE = "POSITIVE", "긍정"
    NEGATIVE = "NEGATIVE", "부정"
    MIXED = "MIXED", "혼합"


class AspectSentiment(models.TextChoices):
    POSITIVE = "POSITIVE", "긍정"
    NEGATIVE = "NEGATIVE", "부정"
