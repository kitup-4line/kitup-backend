from datetime import time, timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from menu_tests.models import MenuTest


def make_test(**fields) -> MenuTest:
    base = dict(
        menu_name="매콤 소스 덮밥",
        selling_price=12000,
        business_start_time=time(11),
        business_end_time=time(20),
    )
    base.update(fields)
    return MenuTest.objects.create(**base)


def make_frozen_test(**fields) -> MenuTest:
    now = timezone.now()
    return make_test(started_at=now - timedelta(days=14), ended_at=now, **fields)


def url(name, test_id=None) -> str:
    return reverse(name, kwargs={"test_id": test_id} if test_id is not None else None)


INGREDIENTS = [
    {"ingredient_name": "돼지고기", "quantity": 150, "unit": "g", "ingredient_cost": 2400},
    {"ingredient_name": "묵은지", "quantity": 80, "unit": "g", "ingredient_cost": "1800.5"},
]
INGREDIENTS_TOTAL = Decimal("4200.5")
