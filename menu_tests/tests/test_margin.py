from decimal import Decimal

from django.test import SimpleTestCase

from core.calc.margin import delivery_margin, pickup_margin


class MarginTests(SimpleTestCase):
    def test_delivery_margin(self):
        result = delivery_margin(12000, Decimal("4200.5"), Decimal("1000"))
        self.assertEqual(result.commission_amount, Decimal("1176"))
        self.assertEqual(result.total_cost, Decimal("9576.5"))
        self.assertEqual(result.contribution_margin, Decimal("2424"))

    def test_pickup_margin(self):
        result = pickup_margin(12000, Decimal("4200.5"), Decimal("1000"))
        self.assertEqual(result.total_cost, Decimal("5200.5"))
        self.assertEqual(result.contribution_margin, Decimal("6800"))

    def test_commission_rounds_half_up(self):
        # 12345 x 0.098 = 1209.81 -> 1210
        self.assertEqual(delivery_margin(12345, 0, 0).commission_amount, Decimal("1210"))

    def test_report_precision_preserves_fractional_cost_and_commission(self):
        result = delivery_margin(12345, Decimal("4200.1234"), Decimal("1000.5678"), round_result=False)
        self.assertEqual(result.commission_amount, Decimal("1209.810"))
        self.assertEqual(result.total_cost + result.contribution_margin, Decimal("12345"))
        result = pickup_margin(12345, Decimal("4200.1234"), Decimal("1000.5678"), round_result=False)
        self.assertEqual(result.contribution_margin, Decimal("7144.3088"))
