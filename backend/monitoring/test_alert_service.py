from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from monitoring.models import (
    AlertNotification,
    County,
    EnvironmentalObservation,
    FloodPrediction,
)
from monitoring.services.alert_service import (
    AlertServiceError,
    create_high_risk_alert,
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

    def test_high_risk_alert_is_created_pending(self):
        result = create_high_risk_alert(
            self.high_prediction,
            channel="IN_APP",
            recipient="dashboard",
        )

        self.assertTrue(result.created)
        self.assertEqual(result.alert.status, "PENDING")
        self.assertIsNone(result.alert.sent_at)
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
        