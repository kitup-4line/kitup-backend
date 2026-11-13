from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("orders", "0001_initial")]

    operations = [
        migrations.RemoveConstraint("review", "reviews_content_nonblank"),
        migrations.AddConstraint(
            "review",
            models.CheckConstraint(
                condition=models.Q(content__regex=r"[^\s\u3000]"),
                name="reviews_content_nonblank",
            ),
        ),
    ]
