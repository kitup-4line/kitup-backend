from datetime import date, timedelta
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.lookups import Exact
from django.utils import timezone

from core.choices import (
    IngredientUnit,
    RecommendationStatus,
    ReviewAnalysisStatus,
    TestStatus,
)
from core.constants import SAMPLE_OPERATING_DAYS
from core.models import TimeStampedModel


class MenuTest(TimeStampedModel):
    # TODO(팀 확인): ERD는 IDENTITY ALWAYS. Django 기본(BY DEFAULT) 유지 중
    id = models.BigAutoField(primary_key=True, db_column="test_id")
    menu_name = models.CharField(max_length=30, null=True, blank=True)
    selling_price = models.IntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)]
    )
    packaging_cost = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("1000"),
        db_default=Decimal("1000"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    business_start_time = models.TimeField(null=True, blank=True)
    business_end_time = models.TimeField(null=True, blank=True)
    total_ingredient_cost = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("1"))],
    )
    # 가상 운영 시작일의 한국 시간 00:00.
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    # 등록 당시 샘플 정보. 이후 JSON을 바꿔도 유지한다.
    kitchen_name = models.CharField(max_length=100, null=True, blank=True)
    monthly_fixed_cost = models.IntegerField(
        null=True, blank=True, validators=[MinValueValidator(0)]
    )
    improvement_result = models.JSONField(null=True, blank=True)
    review_analysis_status = models.CharField(
        max_length=20,
        choices=ReviewAnalysisStatus.choices,
        default=ReviewAnalysisStatus.PENDING,
        db_default=ReviewAnalysisStatus.PENDING,
    )
    improvement_status = models.CharField(
        max_length=20,
        choices=RecommendationStatus.choices,
        default=RecommendationStatus.PENDING,
        db_default=RecommendationStatus.PENDING,
    )

    class Meta:
        db_table = "tests"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kitchen_name__isnull=True)
                    | Q(kitchen_name__regex=r"\S", started_at__isnull=False)
                ),
                name="tests_kitchen_requires_start",
            ),
            models.CheckConstraint(
                condition=Q(menu_name__isnull=True) | Q(menu_name__regex=r"\S"),
                name="tests_menu_name_nonblank",
            ),
            models.CheckConstraint(
                condition=Q(selling_price__gte=1), name="tests_selling_price_min"
            ),
            models.CheckConstraint(
                condition=Q(packaging_cost__gte=0), name="tests_packaging_nonnegative"
            ),
            models.CheckConstraint(
                condition=Q(business_start_time__lt=F("business_end_time")),
                name="tests_business_time_order",
            ),
            models.CheckConstraint(
                condition=Q(total_ingredient_cost__gte=1),
                name="tests_ingredient_cost_min",
            ),
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True)
                | (Q(started_at__isnull=False) & Q(ended_at__gt=F("started_at"))),
                name="tests_operating_time_order",
            ),
            models.CheckConstraint(
                condition=Q(monthly_fixed_cost__gte=0), name="tests_fixed_cost_nonnegative"
            ),
            models.CheckConstraint(
                condition=Q(review_analysis_status__in=ReviewAnalysisStatus.values),
                name="tests_review_analysis_status",
            ),
            models.CheckConstraint(
                condition=Q(improvement_status__in=RecommendationStatus.values),
                name="tests_improvement_status",
            ),
            # 생성 성공 시 JSON 객체 필수.
            models.CheckConstraint(
                condition=~Q(improvement_status=RecommendationStatus.SUCCEEDED)
                | (
                    Q(improvement_result__isnull=False)
                    & Exact(
                        models.Func(
                            F("improvement_result"),
                            function="jsonb_typeof",
                            output_field=models.CharField(),
                        ),
                        Value("object"),
                    )
                ),
                name="tests_succeeded_result_object",
            ),
        ]

    def __str__(self):
        return f"[{self.pk}] {self.menu_name or '(초안)'}"

    @property
    def operating_start_date(self) -> date | None:
        if self.started_at is None:
            return None
        return timezone.localdate(self.started_at, timezone.get_default_timezone())

    @property
    def operating_end_date(self) -> date | None:
        start_date = self.operating_start_date
        if start_date is None:
            return None
        return start_date + timedelta(days=SAMPLE_OPERATING_DAYS - 1)

    @property
    def status(self) -> TestStatus:
        if self.ended_at is not None:
            return TestStatus.COMPLETED
        if self.started_at is not None:
            return TestStatus.RUNNING
        return TestStatus.DRAFT

    @property
    def is_editable(self) -> bool:
        """리포트 생성(ended_at) 전까지만 수정 가능."""
        return self.ended_at is None

    # TODO(팀 확인): 원가 산정 방법(직접/AI)은 저장 안 함. INGREDIENTS 단계 화면 선택은 FE가 결정
    @property
    def resume_step(self) -> str | None:
        """작성 중일 때 이어서 작성할 단계. 그 외 상태는 None."""
        if self.status != TestStatus.DRAFT:
            return None
        basic = (self.menu_name, self.selling_price, self.business_start_time, self.business_end_time)
        if any(value is None for value in basic):
            return "BASIC_INFO"
        if self.total_ingredient_cost is None:
            return "INGREDIENTS"
        return "COST_RESULT"


class Ingredient(TimeStampedModel):
    id = models.BigAutoField(primary_key=True, db_column="ingredient_id")
    test = models.ForeignKey(MenuTest, on_delete=models.CASCADE, related_name="ingredients")
    ingredient_name = models.CharField(max_length=20)
    quantity = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    unit = models.CharField(max_length=10, choices=IngredientUnit.choices)
    # TODO(팀 확인): 화면 라벨은 "구매 단가", ERD는 "사용 비용". 현재는 사용 비용으로 보고 수량 곱하지 않고 합산
    ingredient_cost = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0"))],
        db_comment="구매 단가",
    )

    class Meta:
        db_table = "ingredients"
        constraints = [
            # TODO(팀 확인): ERD는 재료명 전역 UNIQUE. 현재는 같은 테스트 안에서만 중복 금지
            models.UniqueConstraint(
                fields=["test", "ingredient_name"], name="ingredients_test_name_unique"
            ),
            models.CheckConstraint(
                condition=Q(ingredient_name__regex=r"\S"),
                name="ingredients_name_nonblank",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="ingredients_quantity_positive"
            ),
            models.CheckConstraint(
                condition=Q(ingredient_cost__gte=0), name="ingredients_cost_nonnegative"
            ),
            models.CheckConstraint(
                condition=Q(unit__in=IngredientUnit.values), name="ingredients_unit_valid"
            ),
        ]
