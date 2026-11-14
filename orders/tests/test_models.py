from datetime import datetime, timezone as dt_timezone

from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from menu_tests.models import MenuTest
from orders.models import Order, Review


class OrderReviewModelTests(TestCase):
    def setUp(self):
        self.test = MenuTest.objects.create(selling_price=12000)
        self.sample_time = datetime(2026, 10, 20, 3, 30, tzinfo=dt_timezone.utc)
        self.order = self.create_order()

    def create_order(self, **overrides):
        fields = dict(
            test=self.test, sales_amount=12000,
            order_type="DELIVERY", created_at=self.sample_time,
        )
        fields.update(overrides)
        return Order.objects.create(**fields)

    def test_order_without_review_preserves_historical_price_and_time(self):
        MenuTest.objects.filter(pk=self.test.pk).update(selling_price=13000)
        self.order.refresh_from_db()
        self.assertEqual(self.order.sales_amount, 12000)
        self.assertEqual(self.order.created_at, self.sample_time)
        self.assertFalse(Review.objects.filter(order=self.order).exists())

    def test_order_requires_valid_amount_type_and_sample_time(self):
        for overrides in (
            {"sales_amount": 0}, {"sales_amount": -1},
            {"order_type": "CANCELED"}, {"created_at": None},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    self.create_order(**overrides)

    def test_order_foreign_key_is_enforced(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_order(test_id=999999)
            connection.check_constraints()

    def test_review_labels_start_null_and_written_time_is_separate(self):
        review = Review.objects.create(
            order=self.order, content="맛있어요", written_at=self.sample_time
        )
        review.refresh_from_db()
        self.assertEqual(review.written_at, self.sample_time)
        self.assertGreater(review.created_at, review.written_at)
        for field in (
            "sentiment", "taste_sentiment", "portion_sentiment",
            "temperature_sentiment", "packaging_sentiment",
        ):
            self.assertIsNone(getattr(review, field))
        Review.objects.filter(pk=review.pk).update(sentiment="POSITIVE", taste_sentiment="POSITIVE")
        review.refresh_from_db()
        self.assertIsNone(review.portion_sentiment)

    def test_missing_written_time_is_not_replaced_with_now(self):
        review = Review.objects.create(order=self.order, content="맛있어요")
        review.refresh_from_db()
        self.assertIsNone(review.written_at)

    def test_only_one_review_can_belong_to_order(self):
        Review.objects.create(order=self.order, content="첫 리뷰")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(order=self.order, content="두 번째 리뷰")

    def test_blank_review_and_invalid_labels_are_rejected_by_database(self):
        for content in ("", " ", "\t\n", "\u3000", " \u3000\t\n"):
            with self.subTest(content=repr(content)):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    Review.objects.create(order=self.order, content=content)
        review = Review.objects.create(order=self.order, content="\u3000맛은 좋지만 양은 적어요\u3000")
        Review.objects.filter(pk=review.pk).update(
            sentiment="MIXED", taste_sentiment="POSITIVE", portion_sentiment="NEGATIVE"
        )
        for field in (
            "sentiment", "taste_sentiment", "portion_sentiment",
            "temperature_sentiment", "packaging_sentiment",
        ):
            with self.subTest(field=field):
                value = "NEUTRAL" if field == "sentiment" else "MIXED"
                with self.assertRaises(IntegrityError), transaction.atomic():
                    Review.objects.filter(pk=review.pk).update(**{field: value})

    def test_review_foreign_key_is_enforced(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(order_id=999999, content="잘못된 연결")
            connection.check_constraints()

    def test_orm_parent_deletion_removes_owned_children(self):
        Review.objects.create(order=self.order, content="리뷰")
        self.test.delete()
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Review.objects.exists())
