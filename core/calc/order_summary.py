"""주문 실적 집계. DB 조회·저장과 화면별 응답 구성은 호출하는 서비스가 맡는다."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import NotRequired, TypedDict

from django.utils import timezone

from core.calc.margin import delivery_margin, pickup_margin, round_won
from core.choices import Channel
from core.constants import DELIVERY_FEE


class ChannelSummary(TypedDict):
    order_type: Channel
    order_count: int
    revenue: Decimal
    contribution_margin: Decimal
    order_percentage: NotRequired[Decimal | None]
    contribution_margin_per_order: NotRequired[Decimal | None]


class TimeBucket(TypedDict):
    start_time: time
    end_time: time
    order_count: int
    revenue: Decimal
    order_percentage: NotRequired[Decimal | None]
    key: NotRequired[str]
    label: NotRequired[str]


def divide(numerator, denominator) -> Decimal | None:
    return Decimal(numerator) / denominator if denominator else None


def percentage(numerator, denominator) -> Decimal | None:
    return divide(Decimal(numerator) * 100, denominator)


def summarize_orders(orders: list[dict], *, ingredient_cost, packaging_cost) -> dict:
    """dashboard와 같이 건당 공헌이익을 원 단위 반올림한 뒤 합산한다.

    원가 수정 전후 비교도 같은 주문에 원가만 바꿔 호출한다. 입력은 변경하지 않는다.
    """
    channels: dict[Channel, ChannelSummary] = {
        channel: ChannelSummary(
            order_type=channel, order_count=0, revenue=Decimal(0), contribution_margin=Decimal(0),
        )
        for channel in (Channel.DELIVERY, Channel.PICKUP)
    }
    commission = Decimal(0)
    for order in orders:
        channel = channels[order["order_type"]]
        args = (order["sales_amount"], ingredient_cost, packaging_cost)
        if order["order_type"] == Channel.DELIVERY:
            margin = delivery_margin(*args)
            commission += margin.commission_amount
        else:
            margin = pickup_margin(*args)
        channel["order_count"] += 1
        channel["revenue"] += order["sales_amount"]
        channel["contribution_margin"] += margin.contribution_margin

    count = len(orders)
    revenue = sum((channel["revenue"] for channel in channels.values()), Decimal(0))
    contribution = sum((channel["contribution_margin"] for channel in channels.values()), Decimal(0))
    for channel in channels.values():
        channel["order_percentage"] = percentage(channel["order_count"], count)
        channel["contribution_margin_per_order"] = (
            round_won(channel["contribution_margin"] / channel["order_count"])
            if channel["order_count"] else None
        )
    return {
        "order_count": count,
        "revenue": revenue,
        "contribution_margin": contribution,
        "contribution_margin_per_order": round_won(contribution / count) if count else None,
        "costs": {
            "ingredient_cost": Decimal(ingredient_cost) * count,
            "packaging_cost": Decimal(packaging_cost) * count,
            "delivery_fee": Decimal(DELIVERY_FEE) * channels[Channel.DELIVERY]["order_count"],
            "delivery_commission": commission,
        },
        "channels": list(channels.values()),
    }


def sales_by_time(
    orders: list[dict], start_time: time, end_time: time, *, interval_hours: int = 1,
) -> list[TimeBucket]:
    """영업 시작 기준 시간 구간. 종료 경계와 영업시간 밖 주문은 포함하지 않는다."""
    if interval_hours <= 0 or start_time >= end_time:
        raise ValueError("시간 간격은 양수이고 영업 종료는 시작보다 늦어야 합니다.")
    cursor = datetime.combine(date.min, start_time)
    end = datetime.combine(date.min, end_time)
    buckets: list[TimeBucket] = []
    while cursor < end:
        stop = min(cursor + timedelta(hours=interval_hours), end)
        buckets.append({
            "start_time": cursor.time(), "end_time": stop.time(),
            "order_count": 0, "revenue": Decimal(0),
        })
        cursor = stop
    local_timezone = timezone.get_default_timezone()
    for order in orders:
        order_time = timezone.localtime(order["created_at"], local_timezone).time()
        for bucket in buckets:
            if bucket["start_time"] <= order_time < bucket["end_time"]:
                bucket["order_count"] += 1
                bucket["revenue"] += order["sales_amount"]
                break
    for bucket in buckets:
        bucket["order_percentage"] = percentage(bucket["order_count"], len(orders))
    return buckets
