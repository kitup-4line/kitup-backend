"""AI 재료 원가 추정. 성공한 결과만 저장."""

import logging
from decimal import Decimal

from django.conf import settings

from ai import client
from ai.prompts import ingredient_estimate
from ai.schemas import validate_ingredient_estimate
from core.choices import IngredientUnit
from core.exceptions import BasicInfoRequiredError
from menu_tests.models import MenuTest
from menu_tests.services.cost_service import replace_ingredients
from menu_tests.services.menu_test_service import assert_editable

logger = logging.getLogger(__name__)


def assert_ready_for_estimate(test: MenuTest) -> None:
    assert_editable(test)
    if not test.menu_name or test.selling_price is None:
        raise BasicInfoRequiredError()


def estimate_and_save(test: MenuTest, ingredient_names: list[str]) -> MenuTest:
    assert_ready_for_estimate(test)

    # 로컬에서 AI 키 없이 화면 흐름 확인용. DEBUG=False에서는 사용 안 함
    if settings.DEBUG and not settings.AI_API_KEY:
        logger.warning("AI_API_KEY 없음: AI 재료 추정을 mock 값으로 대체함")
        items = [
            {"ingredient_name": name, "quantity": Decimal("100"), "unit": IngredientUnit.GRAM,
             "ingredient_cost": Decimal("1000")}
            for name in ingredient_names
        ]
        return replace_ingredients(test, items)

    # AI 호출은 트랜잭션 밖에서 실행. 실패하면 DB 변경 없음
    user_prompt = ingredient_estimate.build_user_prompt(
        test.menu_name, test.selling_price, ingredient_names, IngredientUnit.values
    )
    payload = client.request_json(ingredient_estimate.SYSTEM_PROMPT, user_prompt)
    items = validate_ingredient_estimate(payload, ingredient_names)
    return replace_ingredients(test, items)
