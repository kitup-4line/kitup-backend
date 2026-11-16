from decimal import Decimal

from rest_framework.test import APITestCase

from .helpers import make_test, url


class CostApiTests(APITestCase):
    def test_cost_summary(self):
        test = make_test(total_ingredient_cost=Decimal("4200.5"))

        res = self.client.get(url("test-cost", test.id))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.json()["data"],
            {
                "selling_price": 12000,
                "total_ingredient_cost": 4200.5,
                "packaging_cost": 1000,
                "delivery_fee": 3200,
                "delivery_commission_rate": 0.098,
                "delivery": {"commission_amount": 1176, "total_cost": 9576.5, "contribution_margin": 2424},
                "pickup": {"total_cost": 5200.5, "contribution_margin": 6800},
            },
        )

    def test_cost_not_ready(self):
        for fields in ({"total_ingredient_cost": None}, {"selling_price": None}):
            with self.subTest(fields=fields):
                test = make_test(**fields)
                res = self.client.get(url("test-cost", test.id))
                self.assertEqual(res.status_code, 409)
                self.assertEqual(res.json()["error"]["code"], "cost_not_ready")

    def test_not_found(self):
        self.assertEqual(self.client.get(url("test-cost", 999999)).status_code, 404)
