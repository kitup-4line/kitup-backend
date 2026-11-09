from decimal import Decimal
from unittest.mock import patch

from rest_framework.test import APITestCase

from core.exceptions import AIServiceError
from menu_tests.models import Ingredient, MenuTest

from .helpers import INGREDIENTS, make_frozen_test, make_test, url

AI_RESPONSE = {
    "ingredients": [
        {"ingredient_name": "묵은지", "quantity": 80, "unit": "g", "ingredient_cost": 1800.123456},
        {"ingredient_name": "돼지고기", "quantity": 150, "unit": "g", "ingredient_cost": 2400},
    ]
}


@patch("ai.client.request_json")
class AIEstimateApiTests(APITestCase):
    def setUp(self):
        self.test = make_test()

    def post(self, names, test_id=None):
        return self.client.post(
            url("test-ingredients-ai-estimate", test_id or self.test.id),
            {"ingredient_names": names},
            format="json",
        )

    def test_success_saves_in_requested_order(self, request_json):
        request_json.return_value = AI_RESPONSE

        res = self.post(["돼지고기", " 묵은지 "])

        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual([row["ingredient_name"] for row in data["ingredients"]], ["돼지고기", "묵은지"])
        self.assertEqual(data["ingredients"][1]["ingredient_cost"], 1800.1235)
        self.test.refresh_from_db()
        self.assertEqual(self.test.total_ingredient_cost, Decimal("4200.1235"))
        system, user = request_json.call_args.args
        self.assertIn("매콤 소스 덮밥", user)
        self.assertIn("묵은지", user)

    def test_name_mismatch_keeps_existing_ingredients(self, request_json):
        self.client.put(url("test-ingredients", self.test.id), {"ingredients": INGREDIENTS}, format="json")
        request_json.return_value = {
            "ingredients": [{"ingredient_name": "대파", "quantity": 10, "unit": "g", "ingredient_cost": 300}]
        }

        res = self.post(["돼지고기", "묵은지"])

        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.json()["error"]["code"], "ai_error")
        self.assertEqual(
            sorted(Ingredient.objects.values_list("ingredient_name", flat=True)), ["돼지고기", "묵은지"]
        )

    def test_invalid_ai_values(self, request_json):
        item = {"ingredient_name": "돼지고기", "quantity": 150, "unit": "g", "ingredient_cost": 2400}
        for payload in (
            {"ingredients": [{**item, "unit": "개"}]},
            {"ingredients": [{**item, "quantity": 0}]},
            {"ingredients": [{**item, "ingredient_cost": 0}]},  # 합계 1 미만
            {"ingredients": [item, item]},  # 중복
            {"ingredients": [{**item, "quantity": 1e40}]},  # 범위 초과가 500이 되지 않아야 함
            {"ingredients": [{**item, "ingredient_cost": 1e30}]},
            {"wrong": []},
        ):
            with self.subTest(payload=payload):
                request_json.return_value = payload
                self.assertEqual(self.post(["돼지고기"]).status_code, 502)
        self.assertFalse(Ingredient.objects.exists())

    def test_client_error_returns_502(self, request_json):
        request_json.side_effect = AIServiceError()
        res = self.post(["돼지고기"])
        self.assertEqual(res.status_code, 502)
        self.assertFalse(Ingredient.objects.exists())

    def test_basic_info_required(self, request_json):
        test = MenuTest.objects.create()
        res = self.post(["돼지고기"], test.id)
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "basic_info_required")
        request_json.assert_not_called()

    def test_frozen(self, request_json):
        test = make_frozen_test()
        res = self.post(["돼지고기"], test.id)
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "frozen")
        request_json.assert_not_called()

    def test_invalid_input(self, request_json):
        for names in ([], ["돼지고기", "돼지고기"], ["  "], ["가" * 21]):
            with self.subTest(names=names):
                self.assertEqual(self.post(names).status_code, 400)
        request_json.assert_not_called()
