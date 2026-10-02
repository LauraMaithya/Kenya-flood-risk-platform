from datetime import date
from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from monitoring.models import (
    AlertNotification,
    County,
    EnvironmentalObservation,
    FloodPrediction,
)
from django.contrib.auth import get_user_model


class MonitoringAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="api-user",
            email="api@example.com",
            password="StrongTestPassword123!",
        )
        self.client.force_authenticate(user=self.user)
        
        self.nairobi = County.objects.create(
            code="047",
            name="Nairobi",
            slug="nairobi",
            latitude=Decimal("-1.286389"),
            longitude=Decimal("36.817223"),
            has_nasa_power_coverage=True,
        )
        self.mombasa = County.objects.create(
            code="001",
            name="Mombasa",
            slug="mombasa",
            latitude=Decimal("-4.043477"),
            longitude=Decimal("39.668206"),
            has_nasa_power_coverage=True,
        )

        self.nairobi_observation = self.create_observation(
            self.nairobi,
            date(2026, 1, 15),
            "047:2026-01-15",
        )
        self.mombasa_observation = self.create_observation(
            self.mombasa,
            date(2026, 1, 16),
            "001:2026-01-16",
        )
        self.synthetic_observation = self.create_observation(
            self.nairobi,
            date(2026, 1, 17),
            "synthetic:047:2026-01-17",
            is_synthetic=True,
        )

        self.high_prediction = self.create_prediction(
            self.nairobi_observation,
            "High",
            "0.10",
            "0.20",
            "0.70",
        )
        self.low_prediction = self.create_prediction(
            self.mombasa_observation,
            "Low",
            "0.80",
            "0.15",
            "0.05",
        )
        self.synthetic_prediction = self.create_prediction(
            self.synthetic_observation,
            "High",
            "0.10",
            "0.20",
            "0.70",
        )

        AlertNotification.objects.create(
            prediction=self.high_prediction,
            channel="IN_APP",
            recipient="dashboard",
            message="High flood risk detected for Nairobi.",
            status="PENDING",
            failure_reason="",
        )
        AlertNotification.objects.create(
            prediction=self.synthetic_prediction,
            channel="IN_APP",
            recipient="dashboard",
            message="Synthetic alert.",
            status="PENDING",
            failure_reason="",
        )

    def create_observation(
        self,
        county,
        observation_date,
        record_id,
        *,
        is_synthetic=False,
    ):
        return EnvironmentalObservation.objects.create(
            county=county,
            observation_date=observation_date,
            precipitation_max_mm=Decimal("42.5"),
            temperature_mean_c=Decimal("24.8"),
            relative_humidity_mean_pct=Decimal("71.2"),
            soil_wetness_mean_fraction=Decimal("0.48"),
            soil_wetness_max_fraction=Decimal("0.63"),
            month_sin=Decimal("0.50000000"),
            month_cos=Decimal("0.86602540"),
            source_record_id=record_id,
            is_synthetic=is_synthetic,
            quality_review_required=False,
        )

    def create_prediction(
        self,
        observation,
        risk_level,
        probability_low,
        probability_medium,
        probability_high,
    ):
        return FloodPrediction.objects.create(
            observation=observation,
            risk_level=risk_level,
            probability_low=Decimal(probability_low),
            probability_medium=Decimal(probability_medium),
            probability_high=Decimal(probability_high),
            model_release_id="kenya_flood_risk_rf_v1_0_0",
            decision_rule="HIGH_THRESHOLD_0.44",
            high_probability_threshold=Decimal("0.44"),
        )

    def test_health_endpoint(self):
        response = self.client.get(
            reverse("monitoring-api:health")
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ok")

    def test_county_list_and_detail_endpoints(self):
        list_response = self.client.get(
            reverse("monitoring-api:county-list")
        )

        self.assertEqual(
            list_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(list_response.data["count"], 2)
        self.assertEqual(
            [
                row["name"]
                for row in list_response.data["results"]
            ],
            ["Mombasa", "Nairobi"],
        )

        detail_response = self.client.get(
            reverse(
                "monitoring-api:county-detail",
                kwargs={"slug": "nairobi"},
            )
        )

        self.assertEqual(
            detail_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            detail_response.data["code"],
            "047",
        )

    def test_observations_filter_and_exclude_synthetic(self):
        response = self.client.get(
            reverse("monitoring-api:observation-list"),
            {"county": "047"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["county_name"],
            "Nairobi",
        )
        self.assertEqual(
            response.data["results"][0]["observation_date"],
            "2026-01-15",
        )

    def test_invalid_observation_date_is_rejected(self):
        response = self.client.get(
            reverse("monitoring-api:observation-list"),
            {"date_from": "15-01-2026"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("date_from", response.data)

    def test_predictions_filter_and_exclude_synthetic(self):
        response = self.client.get(
            reverse("monitoring-api:prediction-list"),
            {"risk_level": "High"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["county_code"],
            "047",
        )
        self.assertEqual(
            response.data["results"][0]["risk_level"],
            "High",
        )

    def test_invalid_risk_level_is_rejected(self):
        response = self.client.get(
            reverse("monitoring-api:prediction-list"),
            {"risk_level": "Extreme"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("risk_level", response.data)

    def test_alert_endpoint_excludes_private_and_synthetic_data(self):
        response = self.client.get(
            reverse("monitoring-api:alert-list"),
            {
                "channel": "IN_APP",
                "status": "PENDING",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        alert = response.data["results"][0]

        self.assertEqual(alert["county_name"], "Nairobi")
        self.assertNotIn("recipient", alert)
        self.assertNotIn("failure_reason", alert)

    def test_api_is_read_only(self):
        response = self.client.post(
            reverse("monitoring-api:county-list"),
            {
                "code": "999",
                "name": "Test County",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )