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


def is_mock_enabled() -> bool:
    # 로컬 화면 개발용. DEBUG=False에서는 설정을 켜도 사용 안 함
    return settings.DEBUG and settings.AI_MOCK_ENABLED


def estimate_and_save(test: MenuTest, ingredient_names: list[str]) -> tuple[MenuTest, bool]:
    """(저장된 테스트, 목업 여부) 반환."""
    assert_ready_for_estimate(test)
    # AI 호출 중 다른 수정이 있었는지 저장 직전에 비교하기 위한 기준값
    started_updated_at = test.updated_at

    if is_mock_enabled():
        logger.warning("AI_MOCK_ENABLED: AI 재료 추정을 목업 값으로 대체함")
        items = [
            {"ingredient_name": name, "quantity": Decimal("100"), "unit": IngredientUnit.GRAM,
             "ingredient_cost": Decimal("1000")}
            for name in ingredient_names
        ]
        return replace_ingredients(test, items, expected_updated_at=started_updated_at), True

    # AI 호출은 트랜잭션 밖에서 실행. 실패하면 DB 변경 없음
    user_prompt = ingredient_estimate.build_user_prompt(
        test.menu_name, test.selling_price, ingredient_names, IngredientUnit.values
    )
    payload = client.request_json(ingredient_estimate.SYSTEM_PROMPT, user_prompt)
    items = validate_ingredient_estimate(payload, ingredient_names)
    return replace_ingredients(test, items, expected_updated_at=started_updated_at), False
