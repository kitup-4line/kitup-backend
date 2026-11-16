from copy import deepcopy
from datetime import UTC, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from core.calc.order_summary import sales_by_time, summarize_orders
from core.choices import Channel


def order(channel=Channel.DELIVERY, price=12000, hour=12, minute=0, day=1):
    return {
        "order_type": channel,
        "sales_amount": price,
        "created_at": datetime(2026, 11, day, hour, minute, tzinfo=ZoneInfo("Asia/Seoul")).astimezone(UTC),
    }


class OrderAggregateTests(SimpleTestCase):
    def test_actual_channel_mix_drives_totals_and_average(self):
        orders = [order() for _ in range(48)] + [order(Channel.PICKUP) for _ in range(12)]
        result = summarize_orders(orders, ingredient_cost=4500, packaging_cost=800)
        self.assertEqual(result["order_count"], 60)
        self.assertEqual(result["revenue"], 720000)
        self.assertEqual(result["contribution_margin"], 191952)
        self.assertEqual(result["contribution_margin_per_order"], Decimal("3199"))
        delivery, pickup = result["channels"]
        self.assertEqual(delivery["contribution_margin_per_order"], 2324)
        self.assertEqual(pickup["contribution_margin_per_order"], 6700)
        self.assertEqual((delivery["order_percentage"], pickup["order_percentage"]), (80, 20))
        self.assertEqual(sum(result["costs"].values()) + result["contribution_margin"], result["revenue"])

    def test_cost_preview_keeps_order_prices_and_inputs(self):
        orders = [order(price=12345), order(Channel.PICKUP, price=9900)]
        original = deepcopy(orders)
        before = summarize_orders(orders, ingredient_cost=Decimal("2800.1234"), packaging_cost=300)
        after = summarize_orders(orders, ingredient_cost=Decimal("2700.0000"), packaging_cost=300)
        self.assertEqual(before["revenue"], 22245)
        self.assertEqual(after["revenue"], 22245)
        self.assertEqual(before["costs"]["delivery_commission"], Decimal("1210"))
        self.assertEqual(after["contribution_margin"] - before["contribution_margin"], Decimal("200"))
        self.assertEqual(after["contribution_margin_per_order"] - before["contribution_margin_per_order"],
                         Decimal("100"))
        self.assertEqual(orders, original)

    def test_empty_orders_and_absent_channel_have_no_average(self):
        empty = summarize_orders([], ingredient_cost=4500, packaging_cost=800)
        self.assertEqual(empty["revenue"], 0)
        self.assertEqual(empty["contribution_margin"], 0)
        self.assertIsNone(empty["contribution_margin_per_order"])
        for channel in empty["channels"]:
            self.assertIsNone(channel["contribution_margin_per_order"])
            self.assertIsNone(channel["order_percentage"])
        result = summarize_orders([order(Channel.PICKUP)], ingredient_cost=4500, packaging_cost=800)
        self.assertEqual(result["costs"]["delivery_fee"], 0)
        self.assertEqual(result["costs"]["delivery_commission"], 0)
        self.assertIsNone(result["channels"][0]["contribution_margin_per_order"])
        self.assertEqual(result["channels"][0]["order_percentage"], 0)


@override_settings(TIME_ZONE="Asia/Seoul")
class TimeAggregateTests(SimpleTestCase):
    def test_hourly_and_two_hour_buckets_share_boundaries_and_totals(self):
        orders = [order(hour=hour, price=1000 + hour) for hour in (10, 11, 12, 13, 18, 19, 20)]
        orders.extend([order(hour=12, minute=59), order(hour=12, day=2)])
        with timezone.override("UTC"):
            hourly = sales_by_time(orders, time(11), time(20))
            two_hour = sales_by_time(orders, time(11), time(20), interval_hours=2)
        self.assertEqual(len(hourly), 9)
        self.assertEqual(len(two_hour), 5)
        self.assertEqual(hourly[1]["order_count"], 3)
        self.assertEqual((two_hour[-1]["start_time"], two_hour[-1]["end_time"]), (time(19), time(20)))
        for index, bucket in enumerate(two_hour):
            corresponding_hours = hourly[index * 2:index * 2 + 2]
            self.assertEqual(bucket["order_count"], sum(row["order_count"] for row in corresponding_hours))
            self.assertEqual(bucket["revenue"], sum(row["revenue"] for row in corresponding_hours))
        self.assertEqual(sum(bucket["order_count"] for bucket in hourly), len(orders) - 2)

    def test_last_short_bucket_and_empty_sales(self):
        buckets = sales_by_time([], time(11), time(14, 30), interval_hours=2)
        self.assertEqual((buckets[-1]["start_time"], buckets[-1]["end_time"]), (time(13), time(14, 30)))
        for bucket in buckets:
            self.assertEqual(bucket["order_count"], 0)
            self.assertIsNone(bucket["order_percentage"])
        buckets = sales_by_time([order(hour=13), order(hour=14, minute=30)], time(11), time(14, 30),
                                interval_hours=2)
        self.assertEqual(buckets[-1]["order_count"], 1)
        self.assertEqual(buckets[-1]["order_percentage"], 50)

    def test_invalid_interval_or_business_hours_fail_without_looping(self):
        for start, end, interval in ((time(11), time(20), 0), (time(11), time(20), -1),
                                     (time(20), time(11), 1), (time(11), time(11), 1)):
            with self.subTest(start=start, end=end, interval=interval), self.assertRaises(ValueError):
                sales_by_time([], start, end, interval_hours=interval)
