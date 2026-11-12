from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("menu_tests", "0002_sample_metadata")]

    operations = [
        migrations.RemoveConstraint("menutest", "tests_fixed_cost_nonnegative"),
        migrations.RenameField("menutest", "monthly_fixed_cost", "additional_fixed_cost"),
        migrations.AddConstraint(
            "menutest",
            models.CheckConstraint(
                condition=models.Q(additional_fixed_cost__gte=0),
                name="tests_fixed_cost_nonnegative",
            ),
        ),
        migrations.AddField(
            "menutest", "report_task_id",
            models.CharField(max_length=32, null=True, blank=True, editable=False),
        ),
    ]
