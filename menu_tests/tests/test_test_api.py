from datetime import time
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from core.constants import SAMPLE_KITCHEN_NAME
from core.exceptions import NotDraftError
from menu_tests.models import Ingredient, MenuTest
from menu_tests.services import menu_test_service

from .helpers import make_frozen_test, make_test, url


class MenuTestListCreateTests(APITestCase):
    def test_empty_list(self):
        res = self.client.get(url("test-list"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"success": True, "message": None, "data": []})

    def test_list_is_latest_first_with_status(self):
        draft = MenuTest.objects.create()
        running = make_test(started_at=timezone.now())

        data = self.client.get(url("test-list")).json()["data"]

        self.assertEqual([row["test_id"] for row in data], [running.id, draft.id])
        self.assertEqual(data[0]["status"], "RUNNING")
        self.assertIsNone(data[0]["resume_step"])
        self.assertEqual(data[0]["kitchen_name"], SAMPLE_KITCHEN_NAME)
        self.assertEqual(data[1]["status"], "DRAFT")
        self.assertEqual(data[1]["resume_step"], "BASIC_INFO")
        self.assertIsNone(data[1]["kitchen_name"])

    def test_list_is_ordered_by_updated_at(self):
        older = make_test()
        newer = make_test()
        self.client.patch(url("test-detail", older.id), {"menu_name": "이어서 작성"}, format="json")

        data = self.client.get(url("test-list")).json()["data"]

        self.assertEqual([row["test_id"] for row in data], [older.id, newer.id])
        self.assertIn("updated_at", data[0])

    def test_create_empty_draft(self):
        res = self.client.post(url("test-list"), {"menu_name": "무시됨"}, format="json")

        self.assertEqual(res.status_code, 201)
        data = res.json()["data"]
        self.assertIsNone(data["menu_name"])
        self.assertEqual(data["packaging_cost"], 1000)
        self.assertEqual(data["status"], "DRAFT")
        self.assertEqual(data["resume_step"], "BASIC_INFO")
        self.assertTrue(data["is_editable"])
        self.assertTrue(MenuTest.objects.filter(pk=data["test_id"]).exists())


class MenuTestDetailTests(APITestCase):
    def test_detail(self):
        test = make_test(total_ingredient_cost=Decimal("4200.5"))

        data = self.client.get(url("test-detail", test.id)).json()["data"]

        self.assertEqual(data["test_id"], test.id)
        self.assertEqual(data["business_start_time"], "11:00")
        self.assertEqual(data["total_ingredient_cost"], 4200.5)
        self.assertEqual(data["resume_step"], "COST_RESULT")

    def test_not_found(self):
        res = self.client.get(url("test-detail", 999999))
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "not_found")


class MenuTestUpdateTests(APITestCase):
    def setUp(self):
        self.test = MenuTest.objects.create()

    def patch(self, body, test_id=None):
        return self.client.patch(url("test-detail", test_id or self.test.id), body, format="json")

    def test_update_basic_info(self):
        res = self.patch({
            "menu_name": "  매콤 소스 덮밥  ",
            "selling_price": 12000,
            "packaging_cost": 800,
            "business_start_time": "11:00",
            "business_end_time": "20:00:00",
            "additional_fixed_cost": 1500000,
            "started_at": "2026-11-01T00:00:00+09:00",
        })

        self.assertEqual(res.status_code, 200)
        self.test.refresh_from_db()
        self.assertEqual(self.test.menu_name, "매콤 소스 덮밥")
        self.assertEqual(self.test.packaging_cost, Decimal("800"))
        self.assertEqual(self.test.business_end_time, time(20))
        self.assertEqual(self.test.additional_fixed_cost, 1500000)
        self.assertIsNone(self.test.started_at)
        self.assertEqual(res.json()["data"]["resume_step"], "INGREDIENTS")

    def test_empty_packaging_cost_saves_zero(self):
        for value in (None, ""):
            with self.subTest(value=value):
                MenuTest.objects.filter(pk=self.test.id).update(packaging_cost=1000)
                res = self.patch({"packaging_cost": value})
                self.assertEqual(res.status_code, 200)
                self.test.refresh_from_db()
                self.assertEqual(self.test.packaging_cost, Decimal("0"))

    def test_invalid_values(self):
        for body in (
            {"menu_name": "   "},
            {"menu_name": None},
            {"menu_name": "가" * 31},
            {"selling_price": 0},
            {"selling_price": None},
            {"packaging_cost": -1},
            {"additional_fixed_cost": -1},
            {"business_start_time": "9시"},
        ):
            with self.subTest(body=body):
                res = self.patch(body)
                self.assertEqual(res.status_code, 400)
                self.assertEqual(res.json()["error"]["code"], "invalid")

    def test_start_must_be_before_end(self):
        res = self.patch({"business_start_time": "20:00", "business_end_time": "20:00"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["message"], "영업 종료 시각은 시작 시각보다 늦어야 합니다.")

    def test_one_time_is_compared_with_saved_time(self):
        test = make_test()  # 11:00 ~ 20:00
        self.assertEqual(self.patch({"business_start_time": "21:00"}, test.id).status_code, 400)
        self.assertEqual(self.patch({"business_end_time": "10:00"}, test.id).status_code, 400)
        self.assertEqual(self.patch({"business_end_time": "22:00"}, test.id).status_code, 200)

    def test_update_total_ingredient_cost_directly(self):
        test = make_test(total_ingredient_cost=Decimal("4200.5"))

        res = self.patch({"total_ingredient_cost": "5000.25"}, test.id)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"]["total_ingredient_cost"], 5000.25)
        # 이후 재료를 저장하면 재료 합계로 덮어씀
        self.client.put(
            url("test-ingredients", test.id),
            {"ingredients": [{"ingredient_name": "대파", "quantity": 10, "unit": "g", "ingredient_cost": 300}]},
            format="json",
        )
        test.refresh_from_db()
        self.assertEqual(test.total_ingredient_cost, Decimal("300"))

    def test_invalid_total_ingredient_cost(self):
        for value in (0, "0.5", None, "1.00001"):
            with self.subTest(value=value):
                self.assertEqual(self.patch({"total_ingredient_cost": value}).status_code, 400)

    def test_frozen(self):
        test = make_frozen_test()
        res = self.patch({"menu_name": "변경"}, test.id)
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "frozen")

    def test_not_found(self):
        self.assertEqual(self.patch({"menu_name": "변경"}, 999999).status_code, 404)


class MenuTestDeleteTests(APITestCase):
    def test_delete_draft_with_ingredients(self):
        test = make_test()
        Ingredient.objects.create(
            test=test, ingredient_name="양파", quantity=1, unit="piece", ingredient_cost=500
        )

        res = self.client.delete(url("test-detail", test.id))

        self.assertEqual(res.status_code, 204)
        self.assertFalse(MenuTest.objects.filter(pk=test.id).exists())
        self.assertFalse(Ingredient.objects.exists())

    def test_started_test_cannot_be_deleted(self):
        test = make_test(started_at=timezone.now())
        res = self.client.delete(url("test-detail", test.id))
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "not_draft")
        self.assertTrue(MenuTest.objects.filter(pk=test.id).exists())

    def test_rechecks_started_at_before_delete(self):
        # 조회 후 삭제 직전에 운영이 시작된 경우
        stale = make_test()
        MenuTest.objects.filter(pk=stale.id).update(started_at=timezone.now())

        with self.assertRaises(NotDraftError):
            menu_test_service.delete_draft(stale)
        self.assertTrue(MenuTest.objects.filter(pk=stale.id).exists())

    def test_not_found(self):
        self.assertEqual(self.client.delete(url("test-detail", 999999)).status_code, 404)


class TestDefaultsTests(APITestCase):
    def test_defaults(self):
        data = self.client.get(url("test-defaults")).json()["data"]
        self.assertEqual(data["packaging_cost"], 1000)
        self.assertEqual(data["delivery_fee"], 3200)
        self.assertEqual(data["delivery_commission_rate"], 0.098)
        self.assertEqual(len(data["business_hour_options"]), 24)
        self.assertEqual(
            [option["value"] for option in data["ingredient_unit_options"]],
            ["g", "kg", "ml", "l", "piece"],
        )
