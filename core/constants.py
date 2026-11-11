from decimal import Decimal

from .choices import IngredientUnit


DELIVERY_COMMISSION_RATE = Decimal("0.098")   # 배달 수수료 9.8%
DELIVERY_FEE = 3200                           # 가게 부담 배달비
DEFAULT_PACKAGING_COST = 1000
DEFAULT_ADDITIONAL_FIXED_COST = 0
SAMPLE_OPERATING_DAYS = 14

# TODO: 와이어프레임 기준으로 확정
OPERATING_HOUR_CHOICES = [f"{h:02d}:00" for h in range(0, 24)]
INGREDIENT_UNIT_CHOICES = IngredientUnit.values

# TODO: orders/fixtures/sample_package.json의 kitchen_name과 맞춰야 함
SAMPLE_KITCHEN_NAME = "성수 공유주방 A"
