"""가상 주문·리뷰, 등록 당시 정보와 운영 시작을 함께 저장한다."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from core.exceptions import AlreadyImportedError, FrozenError, ImportNotReadyError
from menu_tests.models import MenuTest
from orders.models import Order, Review
from orders.serializers import SamplePackageSerializer

SAMPLE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "sample_package.json"


def load_sample_package() -> dict:
    # 파일 읽기와 검증은 DB 행 잠금 전에 끝낸다.
    try:
        data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        serializer = SamplePackageSerializer(data=data)
        serializer.is_valid(raise_exception=True)
    except (OSError, UnicodeError, ValueError, ValidationError) as exc:
        raise ImproperlyConfigured("주문·리뷰 샘플 파일을 확인해주세요.") from exc
    return serializer.validated_data


def import_sample(test_id: int) -> dict:
    package = load_sample_package()
    with transaction.atomic():
        try:
            test = MenuTest.objects.select_for_update().get(pk=test_id)
        except MenuTest.DoesNotExist:
            raise NotFound("테스트를 찾을 수 없습니다.") from None
        # null=True 필드를 IDE가 datetime으로만 추론하는 경우를 보완한다.
        ended_at = cast(datetime | None, test.ended_at)
        started_at = cast(datetime | None, test.started_at)
        if ended_at is not None:
            raise FrozenError()
        if started_at is not None or test.orders.exists():
            raise AlreadyImportedError()
        if (
            not test.menu_name or not test.menu_name.strip()
            or test.selling_price is None or test.selling_price < 1
            or test.business_start_time is None or test.business_end_time is None
            or test.business_start_time >= test.business_end_time
            or test.total_ingredient_cost is None or test.total_ingredient_cost < 1
        ):
            raise ImportNotReadyError()

        imported_at = timezone.now()
        end_date = timezone.localdate(imported_at)
        offset = timedelta(days=(end_date - package["period"]["end_date"]).days)
        start_date = package["period"]["start_date"] + offset
        orders = Order.objects.bulk_create([
            Order(
                test=test,
                # 가상 주문 한 건은 현재 메뉴 한 개. 샘플의 예시 금액은 사용하지 않는다.
                sales_amount=test.selling_price,
                order_type=item["order_type"],
                created_at=item["created_at"] + offset,
            )
            for item in package["orders"]
        ])
        order_map = {
            item["sample_order_id"]: order
            for item, order in zip(package["orders"], orders, strict=True)
        }
        reviews = Review.objects.bulk_create([
            Review(
                order=order_map[item["sample_order_id"]],
                content=item["content"],
                written_at=item["written_at"] + offset,
            )
            for item in package["reviews"]
        ])
        test.kitchen_name = package["kitchen_name"]
        test.sample_start_date = start_date
        test.sample_end_date = end_date
        test.started_at = imported_at
        test.save(update_fields=[
            "kitchen_name", "sample_start_date", "sample_end_date",
            "started_at", "updated_at",
        ])

    return {
        "test_id": test.pk,
        "status": test.status,
        "started_at": test.started_at,
        "kitchen_name": test.kitchen_name,
        "period": {
            "start_date": test.sample_start_date,
            "end_date": test.sample_end_date,
            "operating_days": (test.sample_end_date - test.sample_start_date).days + 1,
        },
        "order_count": len(orders),
        "review_count": len(reviews),
    }
