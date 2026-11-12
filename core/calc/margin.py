"""채널별 변동비·건당 공헌이익. FE domain/calc와 같은 공식 유지."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from core.constants import DELIVERY_COMMISSION_RATE, DELIVERY_FEE

WON = Decimal("1")


def round_won(value: Decimal) -> Decimal:
    return value.quantize(WON, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class DeliveryMargin:
    commission_amount: Decimal
    total_cost: Decimal
    contribution_margin: Decimal


@dataclass(frozen=True)
class PickupMargin:
    total_cost: Decimal
    contribution_margin: Decimal


def delivery_margin(
    selling_price,
    ingredient_cost,
    packaging_cost,
    commission_rate=DELIVERY_COMMISSION_RATE,
    delivery_fee=DELIVERY_FEE,
    *,
    round_result=True,
) -> DeliveryMargin:
    price = Decimal(selling_price)
    commission = price * Decimal(commission_rate)
    if round_result:
        commission = round_won(commission)
    total = Decimal(ingredient_cost) + Decimal(packaging_cost) + Decimal(delivery_fee) + commission
    margin = price - total
    return DeliveryMargin(commission, total, round_won(margin) if round_result else margin)


def pickup_margin(selling_price, ingredient_cost, packaging_cost, *, round_result=True) -> PickupMargin:
    """픽업은 식재료비와 포장비만 차감한다."""
    price = Decimal(selling_price)
    total = Decimal(ingredient_cost) + Decimal(packaging_cost)
    margin = price - total
    return PickupMargin(total, round_won(margin) if round_result else margin)
