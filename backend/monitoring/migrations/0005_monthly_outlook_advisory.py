import django.db.models.deletion
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("monitoring", "0004_alert_acknowledgement_and_test_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="MonthlyOutlookAdvisory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_month", models.DateField()),
                ("issued_on", models.DateField()),
                ("probability_high", models.DecimalField(decimal_places=6, max_digits=7)),
                ("channel", models.CharField(choices=[("IN_APP", "In-app"), ("EMAIL", "Email")], max_length=20)),
                ("recipient", models.CharField(max_length=255)),
                ("message", models.TextField()),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("SENT", "Sent"), ("FAILED", "Failed")], default="PENDING", max_length=20)),
                ("failure_reason", models.TextField(blank=True, default="")),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("acknowledged_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="acknowledged_monthly_outlook_advisories", to=settings.AUTH_USER_MODEL)),
                ("county", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="monthly_outlook_advisories", to="monitoring.county")),
            ],
            options={"ordering": ["-issued_on", "target_month", "county__name"]},
        ),
        migrations.AddIndex(
            model_name="monthlyoutlookadvisory",
            index=models.Index(fields=["status", "created_at"], name="outlook_adv_status_idx"),
        ),
        migrations.AddIndex(
            model_name="monthlyoutlookadvisory",
            index=models.Index(fields=["target_month", "county"], name="outlook_adv_target_idx"),
        ),
        migrations.AddConstraint(
            model_name="monthlyoutlookadvisory",
            constraint=models.UniqueConstraint(fields=("county", "target_month", "issued_on", "channel", "recipient"), name="unique_monthly_outlook_advisory"),
        ),
        migrations.AddConstraint(
            model_name="monthlyoutlookadvisory",
            constraint=models.CheckConstraint(condition=models.Q(("probability_high__gte", Decimal("0")), ("probability_high__lte", Decimal("1"))), name="outlook_advisory_probability_range"),
        ),
        migrations.AddConstraint(
            model_name="monthlyoutlookadvisory",
            constraint=models.CheckConstraint(condition=models.Q(("status", "SENT"), _negated=True) | models.Q(("sent_at__isnull", False)), name="sent_outlook_advisory_timestamp"),
        ),
    ]
