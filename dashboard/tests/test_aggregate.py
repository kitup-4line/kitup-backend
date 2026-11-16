from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from core.calc import aggregate
from core.calc.aggregate import OrderRow

KST = ZoneInfo("Asia/Seoul")


def row(order_type, hour, day=2, amount=12000):
    return OrderRow(order_type, amount, datetime(2026, 11, day, hour, 10, tzinfo=KST))


class AggregateTests(SimpleTestCase):
    def test_summarize_uses_channel_margin(self):
        # 배달 2424, 픽업 6800 (판매가 12,000 / 식재료비 4,200.5 / 포장비 1,000)
        orders = [row("DELIVERY", 12), row("DELIVERY", 12), row("PICKUP", 18)]
        result = aggregate.summarize(orders, Decimal("4200.5"), Decimal("1000"))
        self.assertEqual(result["order_count"], 3)
        self.assertEqual(result["sales_amount"], 36000)
        self.assertEqual(result["total_contribution_margin"], Decimal("11648"))
        self.assertEqual(result["average_contribution_margin"], Decimal("3883"))  # 3882.67 반올림

    def test_summarize_empty(self):
        result = aggregate.summarize([], None, Decimal("1000"))
        self.assertEqual(result, {
            "order_count": 0, "sales_amount": 0,
            "total_contribution_margin": Decimal("0"), "average_contribution_margin": None,
        })

    def test_by_hour_sorts_by_count_then_hour(self):
        orders = [row("PICKUP", h) for h in (19, 11, 12, 12, 18, 18)]
        slots = aggregate.by_hour(orders)
        self.assertEqual([s["hour"] for s in slots], [12, 18, 11, 19])
        self.assertEqual(slots[0], {"hour": 12, "order_count": 2, "ratio": Decimal("33.3")})

    def test_by_channel_always_returns_both_channels(self):
        channels = aggregate.by_channel([row("DELIVERY", 12)], Decimal("4200.5"), Decimal("1000"))
        self.assertEqual([c["order_type"] for c in channels], ["PICKUP", "DELIVERY"])
        self.assertEqual(channels[0]["order_count"], 0)
        self.assertIsNone(channels[0]["average_contribution_margin"])
        self.assertEqual(channels[1]["average_contribution_margin"], Decimal("2424"))

    def test_ratio(self):
        self.assertIsNone(aggregate.ratio(1, 0))
        self.assertEqual(aggregate.ratio(42, 60), Decimal("70.0"))
        self.assertEqual(aggregate.ratio(2, 3), Decimal("66.7"))
