"""AI 응답 JSON 검증 스키마."""

from decimal import ROUND_HALF_UP, Decimal

from rest_framework import serializers

from core.choices import IngredientUnit
from core.exceptions import AIServiceError

FOUR_PLACES = Decimal("0.0001")
MAX_QUANTITY = Decimal("9999.9999")
MAX_COST = Decimal("99999999.9999")


class EstimatedIngredientSerializer(serializers.Serializer):
    ingredient_name = serializers.CharField(max_length=20)
    # 반올림은 직접 하므로 자릿수 제한 없이 받음
    quantity = serializers.DecimalField(max_digits=None, decimal_places=None)
    unit = serializers.ChoiceField(choices=IngredientUnit.choices)
    ingredient_cost = serializers.DecimalField(max_digits=None, decimal_places=None)


class IngredientEstimateResponseSerializer(serializers.Serializer):
    ingredients = EstimatedIngredientSerializer(many=True, allow_empty=False)


def _round(value: Decimal) -> Decimal:
    # 너무 큰 값은 quantize에서 InvalidOperation이 나므로 먼저 범위를 확인
    if not value.is_finite() or abs(value) > MAX_COST:
        raise AIServiceError("AI가 추정한 수량 또는 비용이 허용 범위를 벗어났습니다.")
    return value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def validate_ingredient_estimate(payload: dict, requested_names: list[str]) -> list[dict]:
    serializer = IngredientEstimateResponseSerializer(data=payload)
    if not serializer.is_valid():
        raise AIServiceError("AI 응답 형식이 올바르지 않습니다.")

    items = {}
    for item in serializer.validated_data["ingredients"]:
        quantity = _round(item["quantity"])
        cost = _round(item["ingredient_cost"])
        if not (0 < quantity <= MAX_QUANTITY) or not (0 <= cost <= MAX_COST):
            raise AIServiceError("AI가 추정한 수량 또는 비용이 허용 범위를 벗어났습니다.")
        items[item["ingredient_name"]] = {**item, "quantity": quantity, "ingredient_cost": cost}

    # 요청한 재료와 정확히 같아야 함 (누락·추가·중복 불가)
    if len(items) != len(serializer.validated_data["ingredients"]) or set(items) != set(requested_names):
        raise AIServiceError("AI 응답의 재료 목록이 요청과 다릅니다.")

    total = sum(item["ingredient_cost"] for item in items.values())
    if not (1 <= total <= MAX_COST):
        raise AIServiceError("AI가 추정한 식재료비 합계가 허용 범위를 벗어났습니다.")

    return [items[name] for name in requested_names]
