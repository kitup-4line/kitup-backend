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
) -> DeliveryMargin:
    price = Decimal(selling_price)
    commission = round_won(price * Decimal(commission_rate))
    total = Decimal(ingredient_cost) + Decimal(packaging_cost) + Decimal(delivery_fee) + commission
    return DeliveryMargin(commission, total, round_won(price - total))


# TODO(팀 확인): 픽업에 수수료·포장비 적용 여부. 현재는 수수료·배달비 없이 포장비만 포함
def pickup_margin(selling_price, ingredient_cost, packaging_cost) -> PickupMargin:
    price = Decimal(selling_price)
    total = Decimal(ingredient_cost) + Decimal(packaging_cost)
    return PickupMargin(total, round_won(price - total))
