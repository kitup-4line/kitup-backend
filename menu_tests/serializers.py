from decimal import Decimal

from rest_framework import serializers

from core.choices import IngredientUnit, TestStatus
from core.constants import SAMPLE_KITCHEN_NAME

from .models import Ingredient, MenuTest

INT_MAX = 2_147_483_647
MAX_COST = Decimal("99999999.9999")
MAX_INGREDIENTS = 20  # 레시피 직접 입력 화면 최대 행 수
TIME_INPUT_FORMATS = ["%H:%M", "%H:%M:%S"]


def time_field(**kwargs):
    return serializers.TimeField(format="%H:%M", input_formats=TIME_INPUT_FORMATS, **kwargs)


# 응답 ---------------------------------------------------------------


class OperatingPeriodSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    operating_days = serializers.IntegerField()


class _MenuTestBaseSerializer(serializers.ModelSerializer):
    test_id = serializers.IntegerField(source="id", read_only=True)
    status = serializers.ChoiceField(choices=TestStatus.choices, read_only=True)
    resume_step = serializers.CharField(read_only=True, allow_null=True)
    kitchen_name = serializers.SerializerMethodField()

    # TODO(팀 확인): ERD에 공유주방 컬럼 없음. 데이터 불러온 테스트만 샘플 공유주방명 반환
    def get_kitchen_name(self, obj) -> str | None:
        return SAMPLE_KITCHEN_NAME if obj.started_at else None


class MenuTestListSerializer(_MenuTestBaseSerializer):
    # TODO(팀 확인): 주문 수는 orders API 구현 후 annotate(Count("orders"))로 추가
    class Meta:
        model = MenuTest
        fields = [
            "test_id", "menu_name", "status", "resume_step", "kitchen_name",
            "started_at", "ended_at", "created_at", "updated_at",
        ]


class MenuTestDetailSerializer(_MenuTestBaseSerializer):
    business_start_time = time_field(read_only=True)
    business_end_time = time_field(read_only=True)
    is_editable = serializers.BooleanField(read_only=True)

    class Meta:
        model = MenuTest
        fields = [
            "test_id", "menu_name", "selling_price", "packaging_cost",
            "business_start_time", "business_end_time", "total_ingredient_cost",
            "additional_fixed_cost", "status", "resume_step", "is_editable", "kitchen_name",
            "started_at", "ended_at", "created_at", "updated_at",
        ]
        read_only_fields = fields


class IngredientSerializer(serializers.ModelSerializer):
    ingredient_id = serializers.IntegerField(source="id", read_only=True)

    class Meta:
        model = Ingredient
        fields = ["ingredient_id", "ingredient_name", "quantity", "unit", "ingredient_cost"]
        read_only_fields = fields


class IngredientListSerializer(serializers.Serializer):
    total_ingredient_cost = serializers.DecimalField(
        max_digits=12, decimal_places=4, allow_null=True
    )
    ingredients = IngredientSerializer(many=True)


class _UnitOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class TestDefaultsSerializer(serializers.Serializer):
    packaging_cost = serializers.IntegerField()
    delivery_fee = serializers.IntegerField()
    delivery_commission_rate = serializers.DecimalField(max_digits=5, decimal_places=4)
    business_hour_options = serializers.ListField(child=serializers.CharField())
    ingredient_unit_options = _UnitOptionSerializer(many=True)


class _DeliveryCostSerializer(serializers.Serializer):
    commission_amount = serializers.DecimalField(max_digits=14, decimal_places=4)
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=4)
    contribution_margin = serializers.DecimalField(max_digits=14, decimal_places=4)


class _PickupCostSerializer(serializers.Serializer):
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=4)
    contribution_margin = serializers.DecimalField(max_digits=14, decimal_places=4)


class CostSummarySerializer(serializers.Serializer):
    selling_price = serializers.IntegerField()
    total_ingredient_cost = serializers.DecimalField(max_digits=12, decimal_places=4)
    packaging_cost = serializers.DecimalField(max_digits=12, decimal_places=4)
    delivery_fee = serializers.IntegerField()
    delivery_commission_rate = serializers.DecimalField(max_digits=5, decimal_places=4)
    delivery = _DeliveryCostSerializer()
    pickup = _PickupCostSerializer()


# 요청 ---------------------------------------------------------------


class MenuTestUpdateSerializer(serializers.Serializer):
    """PATCH 전용(partial). 보낸 필드만 검증·저장하고 정의되지 않은 필드는 무시."""

    menu_name = serializers.CharField(max_length=30)
    selling_price = serializers.IntegerField(min_value=1, max_value=INT_MAX)
    packaging_cost = serializers.DecimalField(
        max_digits=12, decimal_places=4, min_value=Decimal("0"), allow_null=True
    )
    business_start_time = time_field()
    business_end_time = time_field()
    additional_fixed_cost = serializers.IntegerField(min_value=0, max_value=INT_MAX, allow_null=True)
    total_ingredient_cost = serializers.DecimalField(
        max_digits=12, decimal_places=4, min_value=Decimal("1")
    )

    def to_internal_value(self, data):
        # 포장비 빈 문자열은 null과 같게 처리
        if hasattr(data, "get") and data.get("packaging_cost") == "":
            data = data.copy()
            data["packaging_cost"] = None
        return super().to_internal_value(data)

    def validate_packaging_cost(self, value):
        # 포장비를 비우면 0원으로 저장
        return Decimal("0") if value is None else value

    def validate(self, attrs):
        start = attrs.get("business_start_time", getattr(self.instance, "business_start_time", None))
        end = attrs.get("business_end_time", getattr(self.instance, "business_end_time", None))
        if start is not None and end is not None and start >= end:
            raise serializers.ValidationError(
                {"business_end_time": "영업 종료 시각은 시작 시각보다 늦어야 합니다."}
            )
        return attrs


class IngredientInputSerializer(serializers.Serializer):
    ingredient_name = serializers.CharField(max_length=20)
    quantity = serializers.DecimalField(
        max_digits=8, decimal_places=4, min_value=Decimal("0.0001")
    )
    unit = serializers.ChoiceField(choices=IngredientUnit.choices)
    ingredient_cost = serializers.DecimalField(
        max_digits=12, decimal_places=4, min_value=Decimal("0")
    )


# TODO(팀 확인): 재료별 비용은 0원 허용, 합계는 1원 이상(DB 제약). 모든 재료가 0원이면 400
class IngredientBulkInputSerializer(serializers.Serializer):
    ingredients = IngredientInputSerializer(many=True, allow_empty=False, max_length=MAX_INGREDIENTS)

    def validate_ingredients(self, items):
        names = [item["ingredient_name"] for item in items]
        if len(names) != len(set(names)):
            raise serializers.ValidationError("같은 이름의 재료를 두 번 입력할 수 없습니다.")

        total = sum(item["ingredient_cost"] for item in items)
        if total < 1:
            raise serializers.ValidationError("식재료비 합계는 1원 이상이어야 합니다.")
        if total > MAX_COST:
            raise serializers.ValidationError("식재료비 합계가 너무 큽니다.")
        return items


class AIEstimateInputSerializer(serializers.Serializer):
    ingredient_names = serializers.ListField(
        child=serializers.CharField(max_length=20), min_length=1, max_length=MAX_INGREDIENTS
    )

    def validate_ingredient_names(self, names):
        if len(names) != len(set(names)):
            raise serializers.ValidationError("같은 이름의 재료를 두 번 입력할 수 없습니다.")
        return names
