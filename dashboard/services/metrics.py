"""대시보드 지표 집계. 저장하지 않고 조회할 때 계산해서 원가 수정이 바로 반영됨."""

from django.utils import timezone

from core.calc import aggregate
from core.exceptions import CostNotReadyError
from menu_tests.models import MenuTest

# TODO(팀 확인): Order에 상태 컬럼이 없어 전체 주문을 완료 주문으로 집계함

HOURLY_SLOT_COUNT = 5  # 시간대별 판매 화면에 보여줄 시간대 수
PEAK_SLOT_COUNT = 2


def _orders(test: MenuTest) -> list[aggregate.OrderRow]:
    rows = test.orders.values_list("order_type", "sales_amount", "created_at")
    return [
        aggregate.OrderRow(order_type, amount, timezone.localtime(created_at))
        for order_type, amount, created_at in rows
    ]


def _costs(test: MenuTest, orders) -> tuple:
    # 주문이 있는데 식재료비가 없으면 공헌이익을 계산할 수 없음 (불러오기 조건상 정상 흐름에서는 없음)
    if orders and test.total_ingredient_cost is None:
        raise CostNotReadyError()
    return test.total_ingredient_cost, test.packaging_cost


def summary(test: MenuTest) -> dict:
    orders = _orders(test)
    result = aggregate.summarize(orders, *_costs(test, orders))
    return {
        "completed_order_count": result["order_count"],
        "completed_sales_amount": result["sales_amount"],
        "total_contribution_margin": result["total_contribution_margin"],
        "average_contribution_margin": result["average_contribution_margin"],
        # 추가 고정비는 리포트에서만 차감. 화면 안내 문구용
        "fixed_cost_applied": False,
    }


def hourly_sales(test: MenuTest) -> dict:
    orders = _orders(test)
    slots = aggregate.by_hour(orders)[:HOURLY_SLOT_COUNT]
    # 주문이 많은 상위 2개 시간대 (화면 강조 + 하단 안내 문구용)
    peaks = slots[:PEAK_SLOT_COUNT]
    peak_count = sum(slot["order_count"] for slot in peaks)
    return {
        "total_order_count": len(orders),
        "peak": {
            "hours": sorted(slot["hour"] for slot in peaks),
            "order_count": peak_count,
            "ratio": aggregate.ratio(peak_count, len(orders)),
        } if peaks else None,
        "slots": [{**slot, "is_peak": index < PEAK_SLOT_COUNT} for index, slot in enumerate(slots)],
    }


def channels(test: MenuTest) -> dict:
    orders = _orders(test)
    return {"channels": aggregate.by_channel(orders, *_costs(test, orders))}
