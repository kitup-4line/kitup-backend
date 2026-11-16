"""주문 집계. DB와 무관한 순수 함수 (dashboard, reports 공용)."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from core.calc.margin import delivery_margin, pickup_margin, round_won
from core.choices import Channel

# 화면 표시 순서 (와이어프레임: 픽업 → 배달)
CHANNEL_ORDER = (Channel.PICKUP, Channel.DELIVERY)


@dataclass(frozen=True)
class OrderRow:
    order_type: str
    sales_amount: int
    created_at: datetime  # 한국 시간으로 변환된 값


def ratio(part: int, total: int) -> Decimal | None:
    """백분율, 소수 1자리 반올림."""
    if total == 0:
        return None
    return (Decimal(part) * 100 / total).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def order_margin(order: OrderRow, ingredient_cost, packaging_cost) -> Decimal:
    """주문 1건의 공헌이익. 판매가는 주문 금액, 변동비는 현재 원가 기준."""
    if order.order_type == Channel.DELIVERY:
        return delivery_margin(order.sales_amount, ingredient_cost, packaging_cost).contribution_margin
    return pickup_margin(order.sales_amount, ingredient_cost, packaging_cost).contribution_margin


def summarize(orders: list[OrderRow], ingredient_cost, packaging_cost) -> dict:
    count = len(orders)
    total_margin = sum(
        (order_margin(o, ingredient_cost, packaging_cost) for o in orders), Decimal("0")
    )
    return {
        "order_count": count,
        "sales_amount": sum(o.sales_amount for o in orders),
        "total_contribution_margin": total_margin,
        "average_contribution_margin": round_won(total_margin / count) if count else None,
    }


def by_channel(orders: list[OrderRow], ingredient_cost, packaging_cost) -> list[dict]:
    """주문이 0건인 채널도 포함."""
    rows = []
    for channel in CHANNEL_ORDER:
        summary = summarize(
            [o for o in orders if o.order_type == channel], ingredient_cost, packaging_cost
        )
        rows.append({"order_type": channel, **summary})
    return rows


def by_hour(orders: list[OrderRow]) -> list[dict]:
    """1시간 단위 주문 건수. 건수 내림차순, 같으면 시각 오름차순."""
    counts = Counter(o.created_at.hour for o in orders)
    total = len(orders)
    return [
        {"hour": hour, "order_count": count, "ratio": ratio(count, total)}
        for hour, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
