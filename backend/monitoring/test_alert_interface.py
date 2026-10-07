from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from monitoring.models import (
    AlertNotification,
    County,
    EnvironmentalObservation,
    FloodPrediction,
)


User = get_user_model()
PASSWORD = "M7!qZ9#vR2@kL8$x"


class AlertInterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="alert-interface-user",
            email="alert-interface@example.com",
            password=PASSWORD,
        )
        cls.nairobi = County.objects.create(
            code="047",
            name="Nairobi",
            slug="nairobi",
            latitude=Decimal("-1.286389"),
            longitude=Decimal("36.817223"),
            has_nasa_power_coverage=True,
        )
        cls.mombasa = County.objects.create(
            code="001",
            name="Mombasa",
            slug="mombasa",
            latitude=Decimal("-4.043500"),
            longitude=Decimal("39.668200"),
            has_nasa_power_coverage=True,
        )

    def setUp(self):
        self.url = reverse("monitoring-web:alerts")

    def authenticate(self):
        self.client.force_login(self.user)

    def create_alert(
        self,
        *,
        county,
        observation_date,
        channel=AlertNotification.Channel.IN_APP,
        status=AlertNotification.Status.PENDING,
        is_synthetic=False,
        recipient=None,
        failure_reason="",
    ):
        observation = EnvironmentalObservation.objects.create(
            county=county,
            observation_date=observation_date,
            precipitation_max_mm=Decimal("45.000"),
            temperature_mean_c=Decimal("24.00"),
            relative_humidity_mean_pct=Decimal("78.000"),
            soil_wetness_mean_fraction=Decimal("0.600000"),
            soil_wetness_max_fraction=Decimal("0.800000"),
            month_sin=Decimal("0.50000000"),
            month_cos=Decimal("0.86602540"),
            is_synthetic=is_synthetic,
        )
        prediction = FloodPrediction.objects.create(
            observation=observation,
            risk_level=FloodPrediction.RiskLevel.HIGH,
            probability_low=Decimal("0.100000"),
            probability_medium=Decimal("0.200000"),
            probability_high=Decimal("0.700000"),
            model_release_id="kenya_flood_risk_rf_v1_0_0",
            decision_rule="HIGH_THRESHOLD_0.44",
            high_probability_threshold=Decimal("0.440000"),
        )

        if recipient is None:
            recipient = (
                f"{county.slug}-"
                f"{observation_date.isoformat()}-"
                f"{channel.lower()}"
            )

        sent_at = None
        if status == AlertNotification.Status.SENT:
            sent_at = timezone.now()

        return AlertNotification.objects.create(
            prediction=prediction,
            channel=channel,
            recipient=recipient,
            message=(
                f"High flood risk detected for {county.name} "
                f"on {observation_date.isoformat()}."
            ),
            status=status,
            failure_reason=failure_reason,
            sent_at=sent_at,
        )

    def test_alert_page_requires_authentication(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse("monitoring-web:login"),
            response.url,
        )

    def test_empty_alert_page_is_rendered(self):
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "monitoring/alerts.html",
        )
        self.assertContains(response, "No alerts found")
        self.assertEqual(response.context["result_count"], 0)

    def test_summary_counts_real_alerts_only(self):
        self.create_alert(
            county=self.nairobi,
            observation_date=date(2025, 1, 1),
            status=AlertNotification.Status.PENDING,
        )
        self.create_alert(
            county=self.nairobi,
            observation_date=date(2025, 1, 2),
            status=AlertNotification.Status.SENT,
        )
        self.create_alert(
            county=self.mombasa,
            observation_date=date(2025, 1, 3),
            status=AlertNotification.Status.FAILED,
            failure_reason="Delivery service unavailable.",
        )
        self.create_alert(
            county=self.mombasa,
            observation_date=date(2025, 1, 4),
            is_synthetic=True,
        )
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(
            response.context["total_alert_count"],
            3,
        )
        self.assertEqual(
            response.context["pending_alert_count"],
            1,
        )
        self.assertEqual(
            response.context["sent_alert_count"],
            1,
        )
        self.assertEqual(
            response.context["failed_alert_count"],
            1,
        )

    def test_county_channel_and_status_filters_are_applied(self):
        matching = self.create_alert(
            county=self.nairobi,
            observation_date=date(2025, 2, 1),
            channel=AlertNotification.Channel.EMAIL,
            status=AlertNotification.Status.SENT,
            recipient="nairobi@example.com",
        )
        self.create_alert(
            county=self.nairobi,
            observation_date=date(2025, 2, 2),
            channel=AlertNotification.Channel.IN_APP,
        )
        self.create_alert(
            county=self.mombasa,
            observation_date=date(2025, 2, 3),
            channel=AlertNotification.Channel.EMAIL,
            status=AlertNotification.Status.SENT,
            recipient="mombasa@example.com",
        )
        self.authenticate()

        response = self.client.get(
            self.url,
            {
                "county": "nairobi",
                "channel": "EMAIL",
                "status": "SENT",
            },
        )

        alerts = list(response.context["alerts"])

        self.assertEqual(alerts, [matching])
        self.assertEqual(response.context["result_count"], 1)
        self.assertEqual(
            response.context["sent_alert_count"],
            1,
        )

    def test_failed_alert_displays_failure_reason(self):
        self.create_alert(
            county=self.nairobi,
            observation_date=date(2025, 3, 1),
            status=AlertNotification.Status.FAILED,
            failure_reason="Email provider rejected the request.",
        )
        self.authenticate()

        response = self.client.get(self.url)

        self.assertContains(
            response,
            "Email provider rejected the request.",
        )
        self.assertContains(response, "Failed")

    def test_synthetic_alert_is_not_displayed(self):
        self.create_alert(
            county=self.nairobi,
            observation_date=date(2025, 4, 1),
            is_synthetic=True,
            recipient="synthetic-recipient",
        )
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(response.context["result_count"], 0)
        self.assertContains(response, "No alerts found")

    def test_alert_results_are_paginated_at_25_records(self):
        starting_date = date(2025, 5, 1)

        for offset in range(28):
            self.create_alert(
                county=self.nairobi,
                observation_date=(
                    starting_date + timedelta(days=offset)
                ),
                recipient=f"recipient-{offset}",
            )

        self.authenticate()
        response = self.client.get(self.url)

        self.assertEqual(response.context["result_count"], 28)
        self.assertEqual(len(response.context["alerts"]), 25)
        self.assertTrue(response.context["page_obj"].has_next())

        second_page = self.client.get(
            self.url,
            {"page": 2},
        )

        self.assertEqual(
            len(second_page.context["alerts"]),
            3,
        )