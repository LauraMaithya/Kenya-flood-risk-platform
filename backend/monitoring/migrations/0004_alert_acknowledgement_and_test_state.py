import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("monitoring", "0003_remove_sensorreading_reading_water_level_nonnegative_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="alertnotification",
            name="unique_prediction_alert_recipient",
        ),
        migrations.AddField(
            model_name="alertnotification",
            name="acknowledged_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="alertnotification",
            name="acknowledged_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="acknowledged_alert_notifications",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="alertnotification",
            name="is_test",
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name="alertnotification",
            index=models.Index(
                fields=["channel", "acknowledged_at", "created_at"],
                name="alert_ack_date_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="alertnotification",
            constraint=models.UniqueConstraint(
                fields=("prediction", "channel", "recipient", "is_test"),
                name="unique_prediction_alert_recipient",
            ),
        ),
    ]
