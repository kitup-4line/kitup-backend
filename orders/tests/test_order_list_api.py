from datetime import timedelta
from unittest.mock import patch

from django.db import OperationalError
from django.utils import timezone
from rest_framework.test import APITestCase

from menu_tests.models import MenuTest
from menu_tests.tests.helpers import make_frozen_test, make_test, url
from orders.models import Order, Review
from orders.services import import_service


class OrderListTests(APITestCase):
    def setUp(self):
        self.test = make_test(total_ingredient_cost=4500)
        self.endpoint = url("order-list", self.test.pk)

    def test_list_is_scoped_sorted_and_keeps_saved_amount_and_review(self):
        now = timezone.now().replace(microsecond=0)
        later = Order.objects.create(test=self.test, created_at=now, sales_amount=15000, order_type="DELIVERY")
        earlier = Order.objects.create(test=self.test, created_at=now - timedelta(hours=1), sales_amount=13000, order_type="PICKUP")
        same_time = Order.objects.create(test=self.test, created_at=now, sales_amount=14000, order_type="PICKUP")
        review = Review.objects.create(order=later, content="  맛있어요!\n잘 먹었습니다.  ", written_at=now + timedelta(hours=1))
        legacy_review = Review.objects.create(order=earlier, content="맛있어요", written_at=None)
        other_order = Order.objects.create(test=make_test(), created_at=now, sales_amount=1, order_type="PICKUP")
        Review.objects.create(order=other_order, content="다른 테스트의 리뷰")
        MenuTest.objects.filter(pk=self.test.pk).update(selling_price=20000)

        with self.assertNumQueries(2):
            res = self.client.get(self.endpoint)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])
        self.assertIsNone(res.json()["message"])
        data = res.json()["data"]
        self.assertEqual([row["order_id"] for row in data], [earlier.pk, later.pk, same_time.pk])
        self.assertEqual([row["sales_amount"] for row in data], [13000, 15000, 14000])
        self.assertEqual([row["order_type"] for row in data], ["PICKUP", "DELIVERY", "PICKUP"])
        self.assertEqual(data[0]["review"], {"review_id": legacy_review.pk, "content": "맛있어요", "written_at": None})
        self.assertEqual(data[1]["review"], {
            "review_id": review.pk, "content": review.content,
            "written_at": timezone.localtime(review.written_at).isoformat(),
        })
        self.assertEqual(data[1]["created_at"], timezone.localtime(now).isoformat())
        self.assertIsNone(data[2]["review"])
        self.assertEqual(set(data[1]), {"order_id", "created_at", "order_type", "sales_amount", "review"})

    def test_imported_sixty_orders_include_reviews_without_extra_queries(self):
        import_service.import_sample(self.test.pk)
        self.test.refresh_from_db()
        updated_at = self.test.updated_at
        with self.assertNumQueries(2):
            res = self.client.get(self.endpoint)
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(len(data), 60)
        self.assertEqual(sum(row["review"] is not None for row in data), 48)
        self.assertEqual(sum(row["review"] is None for row in data), 12)
        self.test.refresh_from_db()
        self.assertEqual(self.test.updated_at, updated_at)

    def test_existing_draft_without_orders_returns_empty_list(self):
        res = self.client.get(self.endpoint)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"success": True, "message": None, "data": []})

    def test_completed_test_remains_readable(self):
        test = make_frozen_test()
        order = Order.objects.create(test=test, created_at=test.started_at, sales_amount=12000, order_type="PICKUP")
        res = self.client.get(url("order-list", test.pk))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"][0]["order_id"], order.pk)

    def test_missing_test_returns_404_instead_of_empty_list(self):
        res = self.client.get(url("order-list", 999999))
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.json()["success"])
        self.assertEqual(res.json()["error"]["code"], "not_found")

    def test_database_error_returns_safe_common_json(self):
        # QuerySet 평가 시 발생한 오류도 공통 처리기로 전달되어야 한다.
        def broken_rows():
            yield from ()
            raise OperationalError("private connection detail")

        with patch("orders.views.Order.objects.filter") as query, \
                self.assertLogs("core.exceptions", level="ERROR"):
            query.return_value.select_related.return_value.order_by.return_value = broken_rows()
            res = self.client.get(self.endpoint)
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.json()["error"]["code"], "server_error")
        self.assertNotIn("private connection detail", res.content.decode())
