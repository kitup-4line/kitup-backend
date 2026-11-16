from datetime import time, timedelta
from decimal import Decimal

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from core.choices import IngredientUnit, ReviewAnalysisStatus, TestStatus
from core.constants import INGREDIENT_UNIT_CHOICES
from menu_tests.models import Ingredient, MenuTest


class MenuTestModelTests(TestCase):
    def test_empty_draft_has_defaults_without_children(self):
        test = MenuTest.objects.create()
        test.refresh_from_db()
        self.assertEqual(test.packaging_cost, Decimal("1000"))
        self.assertEqual(test.review_analysis_status, "PENDING")
        self.assertEqual(test.improvement_status, "PENDING")
        self.assertIsNone(test.additional_fixed_cost)
        self.assertIsNone(test.improvement_result)
        self.assertEqual(test.review_quotes, [])
        self.assertEqual(test.status, TestStatus.DRAFT)
        self.assertFalse(test.ingredients.exists())
        self.assertFalse(test.orders.exists())

    def test_fixed_cost_accepts_zero_and_rejects_negative(self):
        test = MenuTest.objects.create(additional_fixed_cost=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MenuTest.objects.filter(pk=test.pk).update(additional_fixed_cost=-1)
        test.refresh_from_db()
        self.assertEqual(test.additional_fixed_cost, 0)

    def test_database_defaults_apply_outside_orm(self):
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO "tests" DEFAULT VALUES RETURNING '
                'test_id, packaging_cost, review_analysis_status, improvement_status, '
                'created_at, updated_at'
            )
            test_id, cost, review_status, improvement_status, created_at, updated_at = cursor.fetchone()
        self.assertEqual(cost, Decimal("1000"))
        self.assertEqual((review_status, improvement_status), ("PENDING", "PENDING"))
        self.assertIsNotNone(created_at)
        self.assertIsNotNone(updated_at)
        self.assertEqual(MenuTest.objects.get(pk=test_id).review_quotes, [])

    def test_invalid_input_is_rejected_without_model_full_clean(self):
        test = MenuTest.objects.create()
        invalid = {
            "selling_price": 0,
            "packaging_cost": Decimal("-0.0001"),
            "total_ingredient_cost": Decimal("0.5"),
            "menu_name": " \t\n",
            "review_analysis_status": "UNKNOWN",
            "improvement_status": "READY",
        }
        for field, value in invalid.items():
            with self.subTest(field=field):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    MenuTest.objects.filter(pk=test.pk).update(**{field: value})

    def test_time_constraints_reject_end_without_start_and_reversed_times(self):
        now = timezone.now()
        for fields in (
            {"ended_at": now},
            {"started_at": now, "ended_at": now - timedelta(seconds=1)},
            {"started_at": now, "ended_at": now},
            {"business_start_time": time(18), "business_end_time": time(9)},
        ):
            with self.subTest(fields=fields):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    MenuTest.objects.create(**fields)

    def test_status_is_derived_without_persisted_status_field(self):
        now = timezone.now()
        test = MenuTest.objects.create(started_at=now)
        self.assertEqual(test.status, TestStatus.RUNNING)
        test.ended_at = now + timedelta(seconds=1)
        test.save(update_fields=["ended_at", "updated_at"])
        self.assertEqual(test.status, TestStatus.COMPLETED)
        self.assertNotIn("status", {field.name for field in MenuTest._meta.fields})

    def test_review_without_samples_can_be_marked_not_required(self):
        test = MenuTest.objects.create(review_analysis_status=ReviewAnalysisStatus.NOT_REQUIRED)
        test.refresh_from_db()
        self.assertEqual(test.review_analysis_status, "NOT_REQUIRED")

    def test_successful_improvement_requires_json_object(self):
        test = MenuTest.objects.create()
        for result in (None, [], "text", 123, True):
            with self.subTest(result=result):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    MenuTest.objects.filter(pk=test.pk).update(
                        improvement_status="SUCCEEDED", improvement_result=result
                    )
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE tests SET improvement_status = 'SUCCEEDED', "
                    "improvement_result = 'null'::jsonb WHERE test_id = %s", [test.pk]
                )
        MenuTest.objects.filter(pk=test.pk).update(
            improvement_status="SUCCEEDED",
            improvement_result={"recommendations": [{"title": "포장 개선"}]},
        )
        test.refresh_from_db()
        self.assertEqual(test.improvement_result["recommendations"][0]["title"], "포장 개선")

class IngredientModelTests(TestCase):
    def setUp(self):
        self.test = MenuTest.objects.create()

    def create_ingredient(self, **overrides):
        fields = dict(
            test=self.test,
            ingredient_name="양파",
            quantity=Decimal("0.1250"),
            unit=IngredientUnit.KILOGRAM,
            ingredient_cost=Decimal("1234.5678"),
        )
        fields.update(overrides)
        return Ingredient.objects.create(**fields)

    def test_name_is_unique_only_within_same_test(self):
        self.create_ingredient()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_ingredient()
        other = MenuTest.objects.create()
        self.create_ingredient(test=other)
        self.assertEqual(Ingredient.objects.count(), 2)

    def test_decimal_values_round_trip_and_zero_price_is_allowed(self):
        ingredient = self.create_ingredient()
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.quantity, Decimal("0.1250"))
        self.assertEqual(ingredient.ingredient_cost, Decimal("1234.5678"))
        Ingredient.objects.filter(pk=ingredient.pk).update(ingredient_cost=0)
        ingredient.refresh_from_db()
        self.assertEqual(ingredient.ingredient_cost, Decimal("0"))

    def test_invalid_units_quantities_and_incomplete_rows_are_rejected(self):
        invalid = (
            {"quantity": 0}, {"quantity": -1}, {"quantity": None},
            {"unit": "L"}, {"unit": "개"}, {"unit": None},
            {"ingredient_cost": -1}, {"ingredient_cost": None},
            {"ingredient_name": " \t\n"},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    self.create_ingredient(**overrides)
        self.assertEqual(INGREDIENT_UNIT_CHOICES, ["g", "kg", "ml", "l", "piece"])

    def test_quantity_precision_range_is_enforced(self):
        self.create_ingredient(quantity=Decimal("9999.9999"))
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.create_ingredient(ingredient_name="마늘", quantity=Decimal("10000"))

    def test_foreign_key_is_enforced(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_ingredient(test_id=999999)
            connection.check_constraints()
