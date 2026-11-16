from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from core.choices import AspectSentiment, Channel, Sentiment
from core.models import TimeStampedModel


class Order(models.Model):
    id = models.BigAutoField(primary_key=True, db_column="order_id")
    test = models.ForeignKey(
        "menu_tests.MenuTest", on_delete=models.CASCADE, related_name="orders"
    )
    sales_amount = models.IntegerField(validators=[MinValueValidator(1)])
    order_type = models.CharField(max_length=20, choices=Channel.choices)
    # 샘플의 주문 발생 시각. DB에 불러오는 현재 시각으로 대체하지 않는다.
    created_at = models.DateTimeField()

    class Meta:
        db_table = "orders"
        constraints = [
            models.CheckConstraint(
                condition=Q(sales_amount__gte=1), name="orders_sales_amount_min"
            ),
            models.CheckConstraint(
                condition=Q(order_type__in=Channel.values), name="orders_type_valid"
            ),
        ]


class Review(TimeStampedModel):
    id = models.BigAutoField(primary_key=True, db_column="review_id")
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="review")
    content = models.TextField()
    written_at = models.DateTimeField(null=True, blank=True)
    sentiment = models.CharField(
        max_length=20, choices=Sentiment.choices, null=True, blank=True
    )
    taste_sentiment = models.CharField(
        max_length=20, choices=AspectSentiment.choices, null=True, blank=True
    )
    portion_sentiment = models.CharField(
        max_length=20, choices=AspectSentiment.choices, null=True, blank=True
    )
    temperature_sentiment = models.CharField(
        max_length=20, choices=AspectSentiment.choices, null=True, blank=True
    )
    packaging_sentiment = models.CharField(
        max_length=20, choices=AspectSentiment.choices, null=True, blank=True
    )

    class Meta:
        db_table = "reviews"
        constraints = [
            models.CheckConstraint(
                # 전각 공백 판정이 DB 로캘에 따라 달라지지 않도록 명시한다.
                condition=Q(content__regex=r"[^\s\u3000]"), name="reviews_content_nonblank"
            ),
            models.CheckConstraint(
                condition=Q(sentiment__in=Sentiment.values), name="reviews_sentiment_valid"
            ),
            models.CheckConstraint(
                condition=Q(taste_sentiment__in=AspectSentiment.values),
                name="reviews_taste_valid",
            ),
            models.CheckConstraint(
                condition=Q(portion_sentiment__in=AspectSentiment.values),
                name="reviews_portion_valid",
            ),
            models.CheckConstraint(
                condition=Q(temperature_sentiment__in=AspectSentiment.values),
                name="reviews_temperature_valid",
            ),
            models.CheckConstraint(
                condition=Q(packaging_sentiment__in=AspectSentiment.values),
                name="reviews_packaging_valid",
            ),
        ]
