from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("menu_tests", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="menutest",
            name="kitchen_name",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddConstraint(
            model_name="menutest",
            constraint=models.CheckConstraint(
                condition=(models.Q(kitchen_name__isnull=True)
                           | models.Q(kitchen_name__regex=r"\S", started_at__isnull=False)),
                name="tests_kitchen_requires_start",
            ),
        ),
    ]
