"""식재료비 합산, 원가 수정, 원가 산정 결과 계산."""

from django.db import transaction

from core.calc.margin import delivery_margin, pickup_margin
from core.constants import DELIVERY_COMMISSION_RATE, DELIVERY_FEE
from core.exceptions import CostNotReadyError, IngredientsChangedError
from menu_tests.models import Ingredient, MenuTest
from menu_tests.services.menu_test_service import assert_editable


@transaction.atomic
def replace_ingredients(test: MenuTest, items: list[dict], expected_updated_at=None) -> MenuTest:
    """재료 전체 교체 후 식재료비 합계 갱신. 직접 입력·AI 추정 공용.

    expected_updated_at: AI 추정처럼 오래 걸리는 요청에서 시작 시점의 updated_at.
    그 사이 테스트가 수정됐으면 덮어쓰지 않고 409.
    """
    # 동시 저장 방지용 행 잠금. 잠근 뒤 Freeze 다시 확인
    locked = MenuTest.objects.select_for_update().get(pk=test.pk)
    assert_editable(locked)
    if expected_updated_at is not None and locked.updated_at != expected_updated_at:
        raise IngredientsChangedError()

    locked.ingredients.all().delete()
    Ingredient.objects.bulk_create(
        Ingredient(
            test=locked,
            ingredient_name=item["ingredient_name"],
            quantity=item["quantity"],
            unit=item["unit"],
            ingredient_cost=item["ingredient_cost"],
        )
        for item in items
    )

    locked.total_ingredient_cost = sum(item["ingredient_cost"] for item in items)
    locked.save(update_fields=["total_ingredient_cost", "updated_at"])
    return locked


def build_cost_summary(test: MenuTest) -> dict:
    if test.selling_price is None or test.total_ingredient_cost is None:
        raise CostNotReadyError()

    delivery = delivery_margin(test.selling_price, test.total_ingredient_cost, test.packaging_cost)
    pickup = pickup_margin(test.selling_price, test.total_ingredient_cost, test.packaging_cost)
    return {
        "selling_price": test.selling_price,
        "total_ingredient_cost": test.total_ingredient_cost,
        "packaging_cost": test.packaging_cost,
        "delivery_fee": DELIVERY_FEE,
        "delivery_commission_rate": DELIVERY_COMMISSION_RATE,
        "delivery": {
            "commission_amount": delivery.commission_amount,
            "total_cost": delivery.total_cost,
            "contribution_margin": delivery.contribution_margin,
        },
        "pickup": {
            "total_cost": pickup.total_cost,
            "contribution_margin": pickup.contribution_margin,
        },
    }
