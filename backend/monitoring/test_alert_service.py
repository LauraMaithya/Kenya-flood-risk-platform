from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.test.utils import override_settings

from monitoring.models import (
    AlertNotification,
    County,
    EnvironmentalObservation,
    FloodPrediction,
)
from monitoring.services.alert_service import (
    AlertServiceError,
    create_high_risk_alert,
    acknowledge_alert,
    deliver_email_alert,
    mark_alert_failed,
    mark_alert_sent,
)


class AlertServiceTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="047",
            name="Nairobi",
            slug="nairobi",
            latitude=Decimal("-1.286389"),
            longitude=Decimal("36.817223"),
            has_nasa_power_coverage=True,
        )

        self.high_observation = self.create_observation(
            date(2026, 1, 15),
            "047:2026-01-15",
        )
        self.medium_observation = self.create_observation(
            date(2026, 1, 16),
            "047:2026-01-16",
        )

        self.high_prediction = FloodPrediction.objects.create(
            observation=self.high_observation,
            risk_level="High",
            probability_low=Decimal("0.10"),
            probability_medium=Decimal("0.20"),
            probability_high=Decimal("0.70"),
            model_release_id="kenya_flood_risk_rf_v1_0_0",
            decision_rule="HIGH_THRESHOLD_0.44",
            high_probability_threshold=Decimal("0.44"),
        )

        self.medium_prediction = FloodPrediction.objects.create(
            observation=self.medium_observation,
            risk_level="Medium",
            probability_low=Decimal("0.20"),
            probability_medium=Decimal("0.70"),
            probability_high=Decimal("0.10"),
            model_release_id="kenya_flood_risk_rf_v1_0_0",
            decision_rule="HIGH_THRESHOLD_0.44",
            high_probability_threshold=Decimal("0.44"),
        )

    def create_observation(self, observation_date, record_id):
        return EnvironmentalObservation.objects.create(
            county=self.county,
            observation_date=observation_date,
            precipitation_max_mm=Decimal("42.5"),
            temperature_mean_c=Decimal("24.8"),
            relative_humidity_mean_pct=Decimal("71.2"),
            soil_wetness_mean_fraction=Decimal("0.48"),
            soil_wetness_max_fraction=Decimal("0.63"),
            month_sin=Decimal("0.50000000"),
            month_cos=Decimal("0.86602540"),
            source_record_id=record_id,
            is_synthetic=False,
            quality_review_required=False,
        )

    def create_alert(self):
        return create_high_risk_alert(
            self.high_prediction,
            channel="IN_APP",
            recipient="dashboard",
        ).alert

    def test_in_app_high_risk_alert_is_available_immediately(self):
        result = create_high_risk_alert(
            self.high_prediction,
            channel="IN_APP",
            recipient="dashboard",
        )

        self.assertTrue(result.created)
        self.assertEqual(result.alert.status, "SENT")
        self.assertIsNotNone(result.alert.sent_at)
        self.assertIn("Nairobi", result.alert.message)
        self.assertIn("2026-01-15", result.alert.message)
        self.assertIn("70.0%", result.alert.message)

    def test_repeated_alert_creation_is_idempotent(self):
        first = create_high_risk_alert(
            self.high_prediction,
            channel="IN_APP",
            recipient="dashboard",
        )
        second = create_high_risk_alert(
            self.high_prediction,
            channel="IN_APP",
            recipient="dashboard",
        )

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(AlertNotification.objects.count(), 1)

    def test_non_high_prediction_is_rejected(self):
        with self.assertRaisesRegex(
            AlertServiceError,
            "only for High-risk",
        ):
            create_high_risk_alert(
                self.medium_prediction,
                channel="IN_APP",
                recipient="dashboard",
            )

    def test_synthetic_prediction_is_rejected_for_operational_alert(self):
        self.high_observation.is_synthetic = True
        self.high_observation.save(update_fields=["is_synthetic"])

        with self.assertRaisesRegex(
            AlertServiceError,
            "synthetic observations",
        ):
            create_high_risk_alert(
                self.high_prediction,
                channel="IN_APP",
                recipient="dashboard",
            )

    def test_invalid_email_recipient_is_rejected(self):
        with self.assertRaisesRegex(
            AlertServiceError,
            "valid email",
        ):
            create_high_risk_alert(
                self.high_prediction,
                channel="EMAIL",
                recipient="not-an-email",
            )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="alerts@example.com",
    )
    def test_email_alert_is_delivered_and_marked_sent(self):
        result = create_high_risk_alert(
            self.high_prediction,
            channel="EMAIL",
            recipient="stakeholder@example.com",
        )

        delivered = deliver_email_alert(result.alert)

        self.assertEqual(delivered.status, "SENT")
        self.assertIsNotNone(delivered.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].to,
            ["stakeholder@example.com"],
        )

    @patch(
        "monitoring.services.alert_service.send_mail",
        side_effect=RuntimeError("SMTP unavailable"),
    )
    def test_email_failure_is_recorded_without_deleting_prediction(
        self,
        mocked_send_mail,
    ):
        result = create_high_risk_alert(
            self.high_prediction,
            channel="EMAIL",
            recipient="stakeholder@example.com",
        )

        delivered = deliver_email_alert(result.alert)

        self.assertEqual(delivered.status, "FAILED")
        self.assertIn("SMTP unavailable", delivered.failure_reason)
        self.assertTrue(
            FloodPrediction.objects.filter(
                pk=self.high_prediction.pk
            ).exists()
        )
        mocked_send_mail.assert_called_once()

    def test_in_app_alert_can_be_acknowledged(self):
        user = get_user_model().objects.create_user(
            username="operator",
            password="Test-password-123!",
        )
        alert = self.create_alert()

        acknowledged = acknowledge_alert(alert, user)

        self.assertIsNotNone(acknowledged.acknowledged_at)
        self.assertEqual(acknowledged.acknowledged_by, user)

    def test_alert_can_be_marked_sent(self):
        alert = self.create_alert()

        alert = mark_alert_sent(alert)

        self.assertEqual(alert.status, "SENT")
        self.assertIsNotNone(alert.sent_at)
        self.assertEqual(alert.failure_reason, "")

    def test_alert_can_be_marked_failed(self):
        alert = self.create_alert()

        alert = mark_alert_failed(
            alert,
            "Email provider unavailable.",
        )

        self.assertEqual(alert.status, "FAILED")
        self.assertIsNone(alert.sent_at)
        self.assertEqual(
            alert.failure_reason,
            "Email provider unavailable.",
        )

    def test_generate_alerts_command_uses_high_risk_only(self):
        output = StringIO()

        call_command(
            "generate_alerts",
            "--all",
            "--channel",
            "IN_APP",
            "--recipient",
            "dashboard",
            stdout=output,
        )

        self.assertIn("1 processed", output.getvalue())
        self.assertIn("1 created", output.getvalue())
        self.assertEqual(AlertNotification.objects.count(), 1)
        self.assertEqual(
            AlertNotification.objects.get().prediction,
            self.high_prediction,
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="alerts@example.com",
        ALERT_EMAIL_RECIPIENTS=["stakeholder@example.com"],
        IN_APP_ALERT_RECIPIENT="platform-users",
    )
    def test_send_test_alert_command_creates_both_marked_channels(self):
        output = StringIO()

        call_command(
            "send_test_alert",
            prediction_id=self.high_prediction.pk,
            stdout=output,
        )

        alerts = AlertNotification.objects.filter(is_test=True)
        self.assertEqual(alerts.count(), 2)
        self.assertEqual(
            set(alerts.values_list("channel", flat=True)),
            {"IN_APP", "EMAIL"},
        )
        self.assertIn("1 emails sent", output.getvalue())

    def test_update_status_command_marks_alert_sent(self):
        alert = self.create_alert()
        output = StringIO()

        call_command(
            "update_alert_status",
            "--alert-id",
            str(alert.pk),
            "--sent",
            stdout=output,
        )

        alert.refresh_from_db()

        self.assertEqual(alert.status, "SENT")
        self.assertIsNotNone(alert.sent_at)
        self.assertIn("updated to SENT", output.getvalue())

