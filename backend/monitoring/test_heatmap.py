from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from monitoring.models import (
    County,
    EnvironmentalObservation,
    FloodPrediction,
)


User = get_user_model()
PASSWORD = "M7!qZ9#vR2@kL8$x"


class DashboardMapAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="map-user",
            email="map@example.com",
            password=PASSWORD,
        )

    def setUp(self):
        self.url = reverse(
            "monitoring-api:dashboard-map"
        )

    def authenticate(self):
        self.client.force_authenticate(user=self.user)

    def create_county(
        self,
        *,
        code,
        name,
        latitude=Decimal("-1.000000"),
        longitude=Decimal("37.000000"),
    ):
        return County.objects.create(
            code=code,
            name=name,
            slug=name.lower().replace(" ", "-"),
            latitude=latitude,
            longitude=longitude,
            has_nasa_power_coverage=True,
        )

    def create_prediction(
        self,
        *,
        county,
        observation_date,
        risk_level,
        is_synthetic=False,
        model_release_id="kenya_flood_risk_rf_v1_0_0",
    ):
        observation = EnvironmentalObservation.objects.create(
            county=county,
            observation_date=observation_date,
            precipitation_max_mm=Decimal("25.000"),
            temperature_mean_c=Decimal("24.00"),
            relative_humidity_mean_pct=Decimal("70.000"),
            soil_wetness_mean_fraction=Decimal("0.400000"),
            soil_wetness_max_fraction=Decimal("0.600000"),
            month_sin=Decimal("0.50000000"),
            month_cos=Decimal("0.86602540"),
            is_synthetic=is_synthetic,
        )

        probabilities = {
            FloodPrediction.RiskLevel.LOW: (
                Decimal("0.700000"),
                Decimal("0.200000"),
                Decimal("0.100000"),
            ),
            FloodPrediction.RiskLevel.MEDIUM: (
                Decimal("0.200000"),
                Decimal("0.600000"),
                Decimal("0.200000"),
            ),
            FloodPrediction.RiskLevel.HIGH: (
                Decimal("0.100000"),
                Decimal("0.200000"),
                Decimal("0.700000"),
            ),
        }

        low, medium, high = probabilities[risk_level]

        return FloodPrediction.objects.create(
            observation=observation,
            risk_level=risk_level,
            probability_low=low,
            probability_medium=medium,
            probability_high=high,
            model_release_id=model_release_id,
            decision_rule="HIGH_THRESHOLD_0.44",
            high_probability_threshold=Decimal("0.440000"),
        )

    def test_map_endpoint_requires_authentication(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_empty_database_returns_empty_results(self):
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_county_without_prediction_is_marked_no_data(self):
        self.create_county(
            code="047",
            name="Nairobi",
        )
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(response.data["count"], 1)

        county = response.data["results"][0]

        self.assertEqual(county["county_name"], "Nairobi")
        self.assertEqual(county["data_status"], "NO_DATA")
        self.assertIsNone(county["risk_level"])
        self.assertIsNone(county["observation_date"])
        self.assertIsNone(county["probability_high"])

    def test_coordinates_are_returned_as_numbers(self):
        self.create_county(
            code="001",
            name="Mombasa",
            latitude=Decimal("-4.043500"),
            longitude=Decimal("39.668200"),
        )
        self.authenticate()

        response = self.client.get(self.url)
        county = response.data["results"][0]

        self.assertIsInstance(county["latitude"], float)
        self.assertIsInstance(county["longitude"], float)
        self.assertTrue(county["has_coordinates"])
        self.assertEqual(county["latitude"], -4.0435)
        self.assertEqual(county["longitude"], 39.6682)

    def test_missing_coordinates_are_explicit(self):
        self.create_county(
            code="002",
            name="Kwale",
            latitude=None,
            longitude=None,
        )
        self.authenticate()

        response = self.client.get(self.url)
        county = response.data["results"][0]

        self.assertFalse(county["has_coordinates"])
        self.assertIsNone(county["latitude"])
        self.assertIsNone(county["longitude"])

    def test_latest_real_prediction_is_selected(self):
        county = self.create_county(
            code="022",
            name="Kiambu",
        )

        self.create_prediction(
            county=county,
            observation_date=date(2026, 8, 1),
            risk_level=FloodPrediction.RiskLevel.MEDIUM,
            model_release_id="release-old",
        )
        self.create_prediction(
            county=county,
            observation_date=date(2026, 9, 1),
            risk_level=FloodPrediction.RiskLevel.HIGH,
            model_release_id="release-current",
        )
        self.create_prediction(
            county=county,
            observation_date=date(2026, 10, 1),
            risk_level=FloodPrediction.RiskLevel.LOW,
            is_synthetic=True,
            model_release_id="release-synthetic",
        )

        self.authenticate()

        response = self.client.get(self.url)
        county_result = response.data["results"][0]

        self.assertEqual(
            county_result["data_status"],
            "AVAILABLE",
        )
        self.assertEqual(
            county_result["risk_level"],
            FloodPrediction.RiskLevel.HIGH,
        )
        self.assertEqual(
            county_result["observation_date"],
            "2026-09-01",
        )
        self.assertEqual(
            county_result["model_release_id"],
            "release-current",
        )

    def test_every_county_appears_once(self):
        nairobi = self.create_county(
            code="047",
            name="Nairobi",
        )
        self.create_county(
            code="001",
            name="Mombasa",
        )

        self.create_prediction(
            county=nairobi,
            observation_date=date(2026, 8, 1),
            risk_level=FloodPrediction.RiskLevel.LOW,
            model_release_id="release-one",
        )
        self.create_prediction(
            county=nairobi,
            observation_date=date(2026, 9, 1),
            risk_level=FloodPrediction.RiskLevel.HIGH,
            model_release_id="release-two",
        )

        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            len(response.data["results"]),
            2,
        )
        self.assertEqual(
            {
                item["county_name"]
                for item in response.data["results"]
            },
            {"Mombasa", "Nairobi"},
        )
    def test_dashboard_contains_heatmap_contract(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("monitoring-web:dashboard")
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertContains(
            response,
            'id="kenya-risk-map"',
        )
        self.assertContains(
            response,
            self.url,
        )
        self.assertContains(
            response,
            "monitoring/js/risk_map.js",
        )
        self.assertContains(
        response,
        "monitoring/data/kenya_adm1.geojson",
        )
        self.assertContains(
            response,
            "leaflet@1.9.4",
        )

    def test_dashboard_contains_county_selector_contract(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("monitoring-web:dashboard")
        )

        self.assertContains(
            response,
            'id="county-selector"',
        )
        self.assertContains(
            response,
            "Select a county to zoom in and view its current risk.",
        )
        self.assertContains(
            response,
            "data-county-risk-card",
        )