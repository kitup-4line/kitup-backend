from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.urls import reverse
from rest_framework.test import APITestCase

from menu_tests.tests.helpers import make_test
from orders.models import Order

KST = ZoneInfo("Asia/Seoul")


def url(name, test_id):
    return reverse(name, kwargs={"test_id": test_id})


def add_order(test, order_type, hour, day=2, amount=12000, tz=KST):
    return Order.objects.create(
        test=test, order_type=order_type, sales_amount=amount,
        created_at=datetime(2026, 11, day, hour, 10, tzinfo=tz),
    )


class DashboardTestBase(APITestCase):
    def setUp(self):
        # 배달 공헌이익 2,424 / 픽업 6,800
        self.test = make_test(
            total_ingredient_cost=Decimal("4200.5"),
            started_at=datetime(2026, 11, 2, tzinfo=KST),
        )

    def get(self, name, test_id=None, **params):
        return self.client.get(url(name, test_id or self.test.id), params)


class SummaryTests(DashboardTestBase):
    def test_summary(self):
        add_order(self.test, "DELIVERY", 12)
        add_order(self.test, "DELIVERY", 12)
        add_order(self.test, "PICKUP", 18)

        data = self.get("dashboard-summary").json()["data"]

        self.assertEqual(data, {
            "completed_order_count": 3,
            "completed_sales_amount": 36000,
            "total_contribution_margin": 11648,
            "average_contribution_margin": 3883,
            "fixed_cost_applied": False,
        })

    def test_uses_saved_order_amount(self):
        add_order(self.test, "PICKUP", 12, amount=10000)
        data = self.get("dashboard-summary").json()["data"]
        self.assertEqual(data["completed_sales_amount"], 10000)
        self.assertEqual(data["total_contribution_margin"], 4800)  # 10,000 - 5,200.5

    def test_cost_change_is_reflected_immediately(self):
        add_order(self.test, "PICKUP", 12)
        before = self.get("dashboard-summary").json()["data"]["total_contribution_margin"]

        self.client.patch(
            reverse("test-detail", kwargs={"test_id": self.test.id}),
            {"total_ingredient_cost": "3200.5"}, format="json",
        )

        after = self.get("dashboard-summary").json()["data"]["total_contribution_margin"]
        self.assertEqual(after - before, 1000)

    def test_no_orders_returns_zeros(self):
        draft = make_test()
        data = self.get("dashboard-summary", draft.id).json()["data"]
        self.assertEqual(data, {
            "completed_order_count": 0,
            "completed_sales_amount": 0,
            "total_contribution_margin": 0,
            "average_contribution_margin": None,
            "fixed_cost_applied": False,
        })

    def test_scoped_to_test(self):
        add_order(make_test(total_ingredient_cost=1), "PICKUP", 12)
        self.assertEqual(self.get("dashboard-summary").json()["data"]["completed_order_count"], 0)


class HourlySalesTests(DashboardTestBase):
    def setUp(self):
        super().setUp()
        for hour in (12, 12, 18, 18, 11, 19, 15):
            add_order(self.test, "PICKUP", hour)

    def test_hourly_sales(self):
        data = self.get("dashboard-hourly-sales").json()["data"]

        self.assertEqual(data["total_order_count"], 7)
        self.assertEqual(data["peak"], {"hours": [12, 18], "order_count": 4, "ratio": 57.1})
        self.assertEqual([s["hour"] for s in data["slots"]], [12, 18, 11, 15, 19])
        self.assertEqual([s["is_peak"] for s in data["slots"]], [True, True, False, False, False])
        self.assertEqual(data["slots"][0], {
            "hour": 12, "label": "12:00 - 13:00", "order_count": 2, "ratio": 28.6, "is_peak": True,
        })

    def test_top_five_slots_only(self):
        add_order(self.test, "PICKUP", 9)  # 6번째 시간대
        data = self.get("dashboard-hourly-sales").json()["data"]
        self.assertEqual(len(data["slots"]), 5)
        self.assertEqual(data["total_order_count"], 8)

    def test_peak_is_top_two_even_without_tie(self):
        # 1위 단독(12시 3건)이어도 2위(18시)까지 묶어서 안내
        add_order(self.test, "PICKUP", 12)
        data = self.get("dashboard-hourly-sales").json()["data"]
        self.assertEqual(data["peak"], {"hours": [12, 18], "order_count": 5, "ratio": 62.5})

    def test_query_params_are_ignored(self):
        data = self.get("dashboard-hourly-sales", limit=1).json()["data"]
        self.assertEqual(len(data["slots"]), 5)

    def test_hour_is_korean_time(self):
        test = make_test(total_ingredient_cost=1)
        add_order(test, "PICKUP", 15, tz=dt_timezone.utc)  # UTC 15:10 = 한국 00:10
        data = self.get("dashboard-hourly-sales", test.id).json()["data"]
        self.assertEqual(data["slots"][0]["label"], "00:00 - 01:00")

    def test_no_orders(self):
        data = self.get("dashboard-hourly-sales", make_test().id).json()["data"]
        self.assertEqual(data, {"total_order_count": 0, "peak": None, "slots": []})


class ChannelComparisonTests(DashboardTestBase):
    def test_channels(self):
        add_order(self.test, "DELIVERY", 12)
        add_order(self.test, "DELIVERY", 13)
        add_order(self.test, "PICKUP", 18)

        data = self.get("dashboard-channels").json()["data"]

        self.assertEqual(data["channels"], [
            {"order_type": "PICKUP", "order_count": 1,
             "contribution_margin_per_order": 6800, "total_contribution_margin": 6800},
            {"order_type": "DELIVERY", "order_count": 2,
             "contribution_margin_per_order": 2424, "total_contribution_margin": 4848},
        ])

    def test_empty_channel_is_included(self):
        add_order(self.test, "DELIVERY", 12)
        pickup = self.get("dashboard-channels").json()["data"]["channels"][0]
        self.assertEqual(pickup, {
            "order_type": "PICKUP", "order_count": 0,
            "contribution_margin_per_order": None, "total_contribution_margin": 0,
        })


class NotFoundTests(APITestCase):
    def test_missing_test(self):
        for name in ("dashboard-summary", "dashboard-hourly-sales", "dashboard-channels"):
            with self.subTest(name=name):
                res = self.client.get(url(name, 999999))
                self.assertEqual(res.status_code, 404)
                self.assertEqual(res.json()["error"]["code"], "not_found")
