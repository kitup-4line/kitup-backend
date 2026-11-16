from django.db import models
from django.db.models.functions import Now


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        abstract = True
