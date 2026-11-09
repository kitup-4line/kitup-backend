from decimal import Decimal

from rest_framework.test import APITestCase

from menu_tests.models import Ingredient

from .helpers import INGREDIENTS, INGREDIENTS_TOTAL, make_frozen_test, make_test, url


class IngredientApiTests(APITestCase):
    def setUp(self):
        self.test = make_test()

    def put(self, ingredients, test_id=None):
        return self.client.put(
            url("test-ingredients", test_id or self.test.id),
            {"ingredients": ingredients},
            format="json",
        )

    def test_empty_list(self):
        data = self.client.get(url("test-ingredients", self.test.id)).json()["data"]
        self.assertEqual(data, {"total_ingredient_cost": None, "ingredients": []})

    def test_save_and_total(self):
        res = self.put(INGREDIENTS)

        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["total_ingredient_cost"], 4200.5)
        self.assertEqual([row["ingredient_name"] for row in data["ingredients"]], ["돼지고기", "묵은지"])
        self.test.refresh_from_db()
        self.assertEqual(self.test.total_ingredient_cost, INGREDIENTS_TOTAL)
        self.assertEqual(self.client.get(url("test-ingredients", self.test.id)).json()["data"], data)

    def test_put_replaces_all(self):
        self.put(INGREDIENTS)
        res = self.put([{"ingredient_name": "대파", "quantity": 10, "unit": "g", "ingredient_cost": 300}])

        self.assertEqual(res.status_code, 200)
        self.assertEqual(list(Ingredient.objects.values_list("ingredient_name", flat=True)), ["대파"])
        self.test.refresh_from_db()
        self.assertEqual(self.test.total_ingredient_cost, Decimal("300"))

    def test_invalid_input(self):
        valid = INGREDIENTS[0]
        cases = {
            "빈 목록": [],
            "30개 초과": [{**valid, "ingredient_name": f"재료{i}"} for i in range(31)],
            "이름 중복": [valid, {**valid, "ingredient_name": " 돼지고기 "}],
            "이름 공백": [{**valid, "ingredient_name": "  "}],
            "이름 20자 초과": [{**valid, "ingredient_name": "가" * 21}],
            "수량 0": [{**valid, "quantity": 0}],
            "수량 범위 초과": [{**valid, "quantity": 10000}],
            "소수 5자리": [{**valid, "quantity": "1.00001"}],
            "잘못된 단위": [{**valid, "unit": "개"}],
            "음수 비용": [{**valid, "ingredient_cost": -1}],
        }
        for name, ingredients in cases.items():
            with self.subTest(name):
                self.assertEqual(self.put(ingredients).status_code, 400)
        self.assertFalse(Ingredient.objects.exists())

    def test_error_message_skips_valid_rows(self):
        # 첫 재료는 정상, 둘째 재료만 오류여도 실제 오류 메시지가 내려가야 함
        res = self.put([INGREDIENTS[0], {**INGREDIENTS[1], "quantity": 0}])
        self.assertEqual(res.status_code, 400)
        self.assertNotEqual(res.json()["error"]["message"], "요청 값을 확인해주세요.")

    def test_total_must_be_at_least_one(self):
        res = self.put([{**INGREDIENTS[0], "ingredient_cost": 0}])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["message"], "식재료비 합계는 1원 이상이어야 합니다.")

    def test_frozen(self):
        test = make_frozen_test()
        res = self.put(INGREDIENTS, test.id)
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "frozen")
        self.assertFalse(Ingredient.objects.exists())

    def test_not_found(self):
        self.assertEqual(self.client.get(url("test-ingredients", 999999)).status_code, 404)
        self.assertEqual(self.put(INGREDIENTS, 999999).status_code, 404)
