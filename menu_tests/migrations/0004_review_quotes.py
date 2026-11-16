from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("menu_tests", "0003_report_fields")]

    operations = [
        migrations.AddField(
            model_name="menutest",
            name="review_quotes",
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
    ]
