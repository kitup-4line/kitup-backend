import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from menu_tests.models import MenuTest
from menu_tests.tests.helpers import make_test, url
from orders.models import Order, Review
from orders.services import import_service


class OrderImportTests(APITestCase):
    def setUp(self):
        self.original_started_at = None
        self.test = make_test(selling_price=15000, total_ingredient_cost=4500, started_at=self.original_started_at)
        self.endpoint = url("order-import-sample", self.test.pk)

    def assert_empty(self):
        self.test.refresh_from_db()
        self.assertEqual(self.test.started_at, self.original_started_at)
        self.assertIsNone(self.test.kitchen_name)
        self.assertFalse(self.test.orders.exists())
        self.assertFalse(Review.objects.exists())

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertFalse(response.json()["success"])
        self.assertEqual(response.json()["error"]["code"], code)

    def test_import_preserves_content_and_times_and_uses_current_price(self):
        package = import_service.load_sample_package()
        # 다른 테스트의 PK가 있어도 샘플 ID를 실제 DB PK로 사용하지 않는다.
        other = make_test()
        Order.objects.create(test=other, sales_amount=1, order_type="PICKUP", created_at=timezone.now())
        imported_at = datetime(2026, 12, 31, 16, 0, tzinfo=dt_timezone.utc)
        offset = timedelta(days=(date(2027, 1, 1) - package["period"]["end_date"]).days)
        old_updated_at = self.test.updated_at
        with patch.object(import_service.timezone, "now", return_value=imported_at):
            res = self.client.post(self.endpoint)
        self.assertEqual(res.status_code, 201, res.content)
        data = res.json()["data"]
        self.assertEqual((data["test_id"], data["status"], data["order_count"], data["review_count"]),
                         (self.test.pk, "RUNNING", 60, 48))
        self.test.refresh_from_db()
        self.assertEqual(timezone.localtime(self.test.started_at).isoformat(), "2026-12-19T00:00:00+09:00")
        self.assertEqual(data["started_at"], "2026-12-19T00:00:00+09:00")
        self.assertEqual(self.test.kitchen_name, package["kitchen_name"])
        self.assertEqual(data["kitchen_name"], package["kitchen_name"])
        self.assertEqual(data["period"], {"start_date": "2026-12-19", "end_date": "2027-01-01", "operating_days": 14})
        self.assertTrue(all(row.created_at >= self.test.started_at for row in self.test.orders.all()))
        self.assertGreater(self.test.updated_at, old_updated_at)
        self.assertEqual(self.test.orders.count(), 60)
        self.assertEqual(self.test.orders.filter(review__isnull=True).count(), 12)
        self.assertEqual(set(self.test.orders.values_list("sales_amount", flat=True)), {15000})
        self.assertFalse(self.test.ingredients.exists())
        mapping = dict(zip(
            [item["sample_order_id"] for item in package["orders"]],
            self.test.orders.order_by("pk"), strict=True,
        ))
        for item in package["reviews"]:
            review = mapping[item["sample_order_id"]].review
            self.assertEqual(review.content, item["content"])
            self.assertEqual(review.written_at, item["written_at"] + offset)
            for field in ("sentiment", "taste_sentiment", "portion_sentiment",
                          "temperature_sentiment", "packaging_sentiment"):
                self.assertIsNone(getattr(review, field))
        for item in package["orders"]:
            self.assertEqual(mapping[item["sample_order_id"]].created_at, item["created_at"] + offset)

    def test_retry_does_not_change_existing_data(self):
        self.client.post(self.endpoint)
        self.test.refresh_from_db()
        started_at = self.test.started_at
        ids = list(self.test.orders.values_list("pk", flat=True))
        self.assert_error(self.client.post(self.endpoint), 409, "already_imported")
        self.test.refresh_from_db()
        self.assertEqual(self.test.started_at, started_at)
        self.assertEqual(list(self.test.orders.values_list("pk", flat=True)), ids)
        self.assertEqual(Review.objects.count(), 48)

    def test_missing_test(self):
        self.assert_error(self.client.post(url("order-import-sample", 999999)), 404, "not_found")

    def test_registered_metadata_survives_later_package_changes(self):
        first = self.client.post(self.endpoint)
        self.assertEqual(first.status_code, 201, first.content)
        original_period = first.json()["data"]["period"]
        original_kitchen = first.json()["data"]["kitchen_name"]
        changed = import_service.load_sample_package()
        changed["kitchen_name"] = "다음 시연 주방"
        later = timezone.now() + timedelta(days=3)
        other = make_test(total_ingredient_cost=1, started_at=self.original_started_at)
        with patch.object(import_service, "load_sample_package", return_value=changed), \
                patch.object(import_service.timezone, "now", return_value=later):
            res = self.client.post(url("order-import-sample", other.pk))
            self.assertEqual(res.status_code, 201, res.content)
            self.assert_error(self.client.post(self.endpoint), 409, "already_imported")
        self.test.refresh_from_db()
        self.assertEqual(self.test.kitchen_name, original_kitchen)
        self.assertEqual(timezone.localdate(self.test.started_at).isoformat(), original_period["start_date"])
        self.assertEqual((timezone.localdate(self.test.started_at) + timedelta(days=13)).isoformat(), original_period["end_date"])
        other.refresh_from_db()
        self.assertEqual(other.kitchen_name, "다음 시연 주방")
        self.assertEqual(timezone.localdate(other.started_at) + timedelta(days=13), timezone.localdate(later))

    def test_import_marker_blocks_retry_even_if_orders_were_removed(self):
        self.assertEqual(self.client.post(self.endpoint).status_code, 201)
        self.test.orders.all().delete()
        self.assert_error(self.client.post(self.endpoint), 409, "already_imported")

    def test_database_rejects_kitchen_without_start_or_blank_name(self):
        for fields in (
            {"kitchen_name": "주방만 저장"},
            {"kitchen_name": "  ", "started_at": timezone.now()},
        ):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                MenuTest.objects.filter(pk=self.test.pk).update(**fields)

    def test_frozen_test(self):
        self.test.started_at = timezone.now() - timedelta(days=14)
        self.test.ended_at = timezone.now()
        self.test.save()
        self.assert_error(self.client.post(self.endpoint), 409, "frozen")
        self.assertFalse(Order.objects.exists())

    def test_required_input_and_optional_fixed_cost(self):
        for field in ("menu_name", "selling_price", "business_start_time",
                      "business_end_time", "total_ingredient_cost"):
            with self.subTest(field=field):
                original = getattr(self.test, field)
                MenuTest.objects.filter(pk=self.test.pk).update(**{field: None})
                self.assert_error(self.client.post(self.endpoint), 409, "import_not_ready")
                self.assert_empty()
                MenuTest.objects.filter(pk=self.test.pk).update(**{field: original})
        for fixed_cost in (None, 0):
            test = make_test(total_ingredient_cost=1, additional_fixed_cost=fixed_cost, started_at=self.original_started_at)
            self.assertEqual(self.client.post(url("order-import-sample", test.pk)).status_code, 201)
            test.refresh_from_db()
            self.assertEqual(test.additional_fixed_cost, fixed_cost)

    def test_invalid_server_sample_is_500_without_writes(self):
        original = json.loads(import_service.SAMPLE_PATH.read_text(encoding="utf-8"))
        variants = []
        for edit in (
            lambda p: p["orders"].pop(),
            lambda p: p["reviews"].pop(),
            lambda p: p["orders"][1].update(sample_order_id=p["orders"][0]["sample_order_id"]),
            lambda p: p["orders"][0].update(order_type="INVALID"),
            lambda p: p["orders"][0].update(created_at="2026-11-10T12:00:00"),
            lambda p: p["reviews"][0].update(sample_order_id=9999),
            lambda p: p["reviews"][0].update(content=" \n"),
            lambda p: p["reviews"][0].update(written_at="2000-01-01T00:00:00+09:00"),
            lambda p: p["reviews"][1].update(sample_order_id=p["reviews"][0]["sample_order_id"]),
            lambda p: p["reviews"][1].update(sample_review_id=p["reviews"][0]["sample_review_id"]),
        ):
            package = deepcopy(original)
            edit(package)
            variants.append(json.dumps(package))
        for body in ["{broken", "null", *variants]:
            with self.subTest(body=body[:40]), patch.object(import_service.Path, "read_text", return_value=body):
                with self.assertLogs("core.exceptions", level="ERROR"):
                    self.assert_error(self.client.post(self.endpoint), 500, "server_error")
                self.assert_empty()

    def test_missing_sample_is_server_error(self):
        with patch.object(import_service.Path, "read_text", side_effect=FileNotFoundError("private/path")):
            with self.assertLogs("core.exceptions", level="ERROR"):
                res = self.client.post(self.endpoint)
        self.assert_error(res, 500, "server_error")
        self.assertNotIn("private/path", res.content.decode())
        self.assert_empty()

    def test_partial_writes_and_metadata_save_are_rolled_back(self):
        original_save = MenuTest.save
        def fail_after_save(instance, *args, **kwargs):
            original_save(instance, *args, **kwargs)
            raise IntegrityError("private SQL detail")

        for target in ("orders", "reviews", "metadata"):
            with self.subTest(target=target):
                old_updated_at = MenuTest.objects.get(pk=self.test.pk).updated_at
                if target == "metadata":
                    mocked = patch.object(MenuTest, "save", fail_after_save)
                else:
                    manager = Order.objects if target == "orders" else Review.objects
                    original_bulk = manager.bulk_create
                    def fail_after_bulk(objects, _original=original_bulk):
                        _original(objects)
                        raise IntegrityError("private SQL detail")
                    mocked = patch.object(manager, "bulk_create", side_effect=fail_after_bulk)
                with mocked, self.assertLogs("core.exceptions", level="ERROR"):
                    res = self.client.post(self.endpoint)
                self.assert_error(res, 500, "server_error")
                self.assertNotIn("private SQL", res.content.decode())
                self.assert_empty()
                self.assertEqual(self.test.updated_at, old_updated_at)

    def test_inconsistent_existing_orders_are_not_overwritten(self):
        order = Order.objects.create(test=self.test, sales_amount=1, order_type="PICKUP", created_at=timezone.now())
        self.assert_error(self.client.post(self.endpoint), 409, "already_imported")
        self.assertEqual(list(self.test.orders.values_list("pk", flat=True)), [order.pk])
        self.test.refresh_from_db()
        self.assertEqual(self.test.started_at, self.original_started_at)
        self.assertIsNone(self.test.kitchen_name)


class OrderImportRequestTests(SimpleTestCase):
    def test_body_is_ignored_and_only_url_id_is_passed_to_service(self):
        result = {
            "test_id": 3, "status": "RUNNING", "started_at": timezone.now(),
            "order_count": 60, "review_count": 48,
            "kitchen_name": "샘플 주방",
            "period": {"start_date": date(2026, 10, 28), "end_date": date(2026, 11, 10), "operating_days": 14},
        }
        client = APIClient()
        bodies = (
            "", "{}", '{"test_id":999,"selling_price":1,"orders":[],"reviews":[]}',
            "[]", "null", "{broken",
        )
        for body in bodies:
            with self.subTest(body=body), patch.object(import_service, "import_sample", return_value=result) as mocked:
                res = client.post(url("order-import-sample", 3), body, content_type="application/json")
                self.assertEqual(res.status_code, 201, res.content)
                mocked.assert_called_once_with(3)
                self.assertEqual(res.json()["data"]["order_count"], 60)
                self.assertEqual(res.json()["data"]["review_count"], 48)
