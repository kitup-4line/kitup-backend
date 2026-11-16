"""공통 주문 집계로 리포트의 세 영역과 시간대 해석을 구성한다. 결과는 저장하지 않는다."""

from datetime import datetime
from decimal import Decimal

from core.calc.order_summary import divide, percentage, sales_by_time, summarize_orders
from core.constants import SAMPLE_OPERATING_DAYS
from core.exceptions import CostNotReadyError, ReportNotReadyError
from orders.models import Review


def build_report(test) -> dict:
    if test.selling_price is None or test.total_ingredient_cost is None:
        raise CostNotReadyError()
    if not all((test.started_at, test.business_start_time, test.business_end_time)):
        raise ReportNotReadyError()
    orders = list(test.orders.order_by("pk").values("sales_amount", "order_type", "created_at"))
    sales = summarize_orders(
        orders, ingredient_cost=test.total_ingredient_cost, packaging_cost=test.packaging_cost,
    )
    count = sales["order_count"]
    revenue = sales["revenue"]
    contribution = sales["contribution_margin"]
    totals = {**sales["costs"], "contribution_margin": contribution}
    fixed_cost = test.additional_fixed_cost or 0
    profit = contribution - fixed_cost
    start = datetime.combine(test.operating_start_date, test.business_start_time)
    end = datetime.combine(test.operating_start_date, test.business_end_time)
    operating_hours = Decimal(str((end - start).total_seconds())) / 3600 * SAMPLE_OPERATING_DAYS
    per_order: dict[str, Decimal | None | dict[str, Decimal | None]] = {
        "average_revenue": divide(revenue, count),
    }
    for name, amount in totals.items():
        per_order[name] = {
            "amount": divide(amount, count),
            "revenue_percentage": percentage(amount, revenue),
        }
    return {
        "analysis_conditions": {
            "operating_period": {
                "start_date": test.operating_start_date,
                "end_date": test.operating_end_date,
                "operating_days": SAMPLE_OPERATING_DAYS,
            },
            "kitchen_name": test.kitchen_name or "",
            "analysis_data": {
                "completed_order_count": count,
                "linked_review_count": Review.objects.filter(order__test=test).count(),
                "channels": [
                    {
                        "order_type": channel["order_type"],
                        "order_count": channel["order_count"],
                        "order_percentage": channel["order_percentage"],
                    }
                    for channel in sales["channels"]
                ],
            },
            "sales_conditions": {
                "selling_price": test.selling_price,
                "business_start_time": test.business_start_time,
                "business_end_time": test.business_end_time,
                "total_operating_hours": operating_hours,
                "orders_per_hour": divide(count, operating_hours),
            },
        },
        "profit_analysis": {
            "summary": {
                "total_revenue": revenue,
                "total_contribution_margin": contribution,
                "contribution_margin_percentage": percentage(contribution, revenue),
                "contribution_margin_per_order": sales["contribution_margin_per_order"],
                "applied_fixed_cost": fixed_cost,
                "estimated_operating_profit": profit,
                "operating_profit_percentage": percentage(profit, revenue),
            },
            "per_order_structure": per_order,
        },
        "sales_pattern": _sales_pattern(orders, test.business_start_time, test.business_end_time, revenue),
    }


def _sales_pattern(orders: list[dict], start_time, end_time, total_revenue: Decimal):
    buckets = sales_by_time(orders, start_time, end_time, interval_hours=2)
    top = sorted(buckets, key=lambda item: (-item["order_count"], item["start_time"]))[:2]
    for bucket in top:
        bucket["key"] = bucket["start_time"].strftime("%H%M")
        bucket["label"] = f"{bucket['start_time']:%H:%M}~{bucket['end_time']:%H:%M}"
    top_count = sum(bucket["order_count"] for bucket in top)
    top_revenue = sum((bucket["revenue"] for bucket in top), Decimal(0))
    other = {
        "key": "other", "label": "기타 시간대", "start_time": None, "end_time": None,
        "order_count": len(orders) - top_count, "revenue": total_revenue - top_revenue,
        "order_percentage": percentage(len(orders) - top_count, len(orders)),
    }
    equal_counts = len({bucket["order_count"] for bucket in buckets}) <= 1
    if not orders:
        result = "분석할 주문이 없습니다."
    elif equal_counts:
        result = "영업시간 내 모든 구간의 주문 건수가 같아 뚜렷한 집중 구간이 없습니다."
    else:
        result = f"주문이 많은 구간은 {', '.join(bucket['label'] for bucket in top)}이며 총 {top_count}건입니다."
    return {
        "time_buckets": [*top, other],
        "peak_summary": {
            "peak_order_count": top_count, "peak_revenue": top_revenue,
            "peak_revenue_percentage": percentage(top_revenue, total_revenue),
        },
        "insights": {
            "result": result,
            "meaning": "영업 시작 기준 2시간 구간의 주문 건수를 비교한 결과입니다.",
            "recommended_action": (
                "주문이 집중된 구간의 재료 준비와 작업 배치를 점검하세요."
                if orders and not equal_counts else None
            ),
            "limitation": (
                "가상 주문 분석으로 실제 수요를 보장하지 않습니다. 마지막 구간은 2시간보다 짧을 수 있으며, "
                "구간 길이를 보정하지 않은 주문 건수 순위입니다. 영업시간 밖 주문은 기타에 포함합니다."
            ),
        },
    }
