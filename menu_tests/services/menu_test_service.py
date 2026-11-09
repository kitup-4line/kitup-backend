"""테스트 조회·수정·삭제 공통 처리."""

from django.db import transaction
from rest_framework.exceptions import NotFound

from core.exceptions import FrozenError, NotDraftError
from menu_tests.models import MenuTest

UPDATABLE_FIELDS = (
    "menu_name",
    "selling_price",
    "packaging_cost",
    "business_start_time",
    "business_end_time",
    "monthly_fixed_cost",
)


def get_test_or_404(test_id) -> MenuTest:
    # Http404 대신 NotFound를 써야 에러 code가 not_found로 내려감
    try:
        return MenuTest.objects.get(pk=test_id)
    except MenuTest.DoesNotExist:
        raise NotFound("테스트를 찾을 수 없습니다.") from None


def assert_editable(test: MenuTest) -> None:
    if not test.is_editable:
        raise FrozenError()


@transaction.atomic
def update_test(test: MenuTest, data: dict) -> MenuTest:
    # 행 잠금 후 Freeze 재확인 (리포트 생성과 동시 요청 방지)
    locked = MenuTest.objects.select_for_update().get(pk=test.pk)
    assert_editable(locked)
    fields = [name for name in UPDATABLE_FIELDS if name in data]
    for name in fields:
        setattr(locked, name, data[name])
    if fields:
        locked.save(update_fields=[*fields, "updated_at"])
    return locked


def delete_draft(test: MenuTest) -> None:
    if test.started_at is not None:
        raise NotDraftError()
    test.delete()
