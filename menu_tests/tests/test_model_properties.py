from datetime import time, timedelta
from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import timezone

from menu_tests.models import MenuTest


class ResumeStepTests(SimpleTestCase):
    def make(self, **fields):
        base = dict(
            menu_name="매콤 소스 덮밥",
            selling_price=12000,
            business_start_time=time(11),
            business_end_time=time(20),
            total_ingredient_cost=Decimal("4200.5"),
        )
        base.update(fields)
        return MenuTest(**base)

    def test_basic_info_missing(self):
        for field in ("menu_name", "selling_price", "business_start_time", "business_end_time"):
            with self.subTest(field=field):
                self.assertEqual(self.make(**{field: None}).resume_step, "BASIC_INFO")

    def test_ingredients_missing(self):
        self.assertEqual(self.make(total_ingredient_cost=None).resume_step, "INGREDIENTS")

    def test_cost_result(self):
        self.assertEqual(self.make().resume_step, "COST_RESULT")

    def test_none_when_not_draft(self):
        now = timezone.now()
        self.assertIsNone(self.make(started_at=now).resume_step)
        self.assertIsNone(self.make(started_at=now, ended_at=now + timedelta(days=1)).resume_step)


class IsEditableTests(SimpleTestCase):
    def test_editable_until_ended(self):
        now = timezone.now()
        self.assertTrue(MenuTest().is_editable)
        self.assertTrue(MenuTest(started_at=now).is_editable)
        self.assertFalse(MenuTest(started_at=now, ended_at=now + timedelta(days=1)).is_editable)
