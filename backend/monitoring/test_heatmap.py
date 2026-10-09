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
    def test_year_and_month_select_latest_period_prediction(self):
        nairobi = self.create_county(
            code="047",
            name="Nairobi",
        )
        mombasa = self.create_county(
            code="001",
            name="Mombasa",
        )

        self.create_prediction(
            county=nairobi,
            observation_date=date(2025, 3, 31),
            risk_level=FloodPrediction.RiskLevel.HIGH,
            model_release_id="march-release",
        )
        self.create_prediction(
            county=nairobi,
            observation_date=date(2025, 4, 10),
            risk_level=FloodPrediction.RiskLevel.MEDIUM,
            model_release_id="april-old-release",
        )
        self.create_prediction(
            county=nairobi,
            observation_date=date(2025, 4, 30),
            risk_level=FloodPrediction.RiskLevel.LOW,
            model_release_id="april-latest-release",
        )
        self.create_prediction(
            county=mombasa,
            observation_date=date(2025, 5, 1),
            risk_level=FloodPrediction.RiskLevel.HIGH,
            model_release_id="may-release",
        )

        self.authenticate()

        response = self.client.get(
            self.url,
            {
                "year": 2025,
                "month": 4,
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["period"],
            {
                "year": 2025,
                "month": 4,
                "label": "April 2025",
                "latest_data_date": "2025-04-30",
            },
        )
        self.assertEqual(
            response.data["summary"],
            {
                "high_risk_count": 0,
                "medium_risk_count": 0,
                "low_risk_count": 1,
                "monitored_count": 1,
            },
        )

        results_by_county = {
            item["county_name"]: item
            for item in response.data["results"]
        }

        self.assertEqual(
            results_by_county["Nairobi"]["risk_level"],
            FloodPrediction.RiskLevel.LOW,
        )
        self.assertEqual(
            results_by_county["Nairobi"]["observation_date"],
            "2025-04-30",
        )
        self.assertEqual(
            results_by_county["Mombasa"]["data_status"],
            "NO_DATA",
        )

    def test_year_selection_uses_latest_prediction_in_year(self):
        county = self.create_county(
            code="022",
            name="Kiambu",
        )

        self.create_prediction(
            county=county,
            observation_date=date(2024, 12, 31),
            risk_level=FloodPrediction.RiskLevel.HIGH,
            model_release_id="2024-release",
        )
        self.create_prediction(
            county=county,
            observation_date=date(2025, 6, 1),
            risk_level=FloodPrediction.RiskLevel.MEDIUM,
            model_release_id="2025-old-release",
        )
        self.create_prediction(
            county=county,
            observation_date=date(2025, 12, 31),
            risk_level=FloodPrediction.RiskLevel.LOW,
            model_release_id="2025-latest-release",
        )

        self.authenticate()

        response = self.client.get(
            self.url,
            {"year": 2025},
        )

        county_result = response.data["results"][0]

        self.assertEqual(
            response.data["period"]["label"],
            "2025",
        )
        self.assertEqual(
            response.data["period"]["latest_data_date"],
            "2025-12-31",
        )
        self.assertEqual(
            county_result["risk_level"],
            FloodPrediction.RiskLevel.LOW,
        )
        self.assertEqual(
            county_result["observation_date"],
            "2025-12-31",
        )

    def test_period_response_lists_available_prediction_years(self):
        county = self.create_county(
            code="030",
            name="Baringo",
        )

        self.create_prediction(
            county=county,
            observation_date=date(2023, 1, 1),
            risk_level=FloodPrediction.RiskLevel.LOW,
            model_release_id="2023-release",
        )
        self.create_prediction(
            county=county,
            observation_date=date(2025, 1, 1),
            risk_level=FloodPrediction.RiskLevel.MEDIUM,
            model_release_id="2025-release",
        )

        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(
            response.data["available_years"],
            [2025, 2023],
        )
        self.assertEqual(
            response.data["period"]["label"],
            "Latest available",
        )

    def test_month_requires_year(self):
        self.authenticate()

        response = self.client.get(
            self.url,
            {"month": 4},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("month", response.data)

    def test_invalid_period_parameters_are_rejected(self):
        self.authenticate()

        invalid_parameters = [
            {"year": "not-a-year"},
            {"year": 2025, "month": 0},
            {"year": 2025, "month": 13},
        ]

        for parameters in invalid_parameters:
            with self.subTest(parameters=parameters):
                response = self.client.get(
                    self.url,
                    parameters,
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_400_BAD_REQUEST,
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
            "monitoring/vendor/leaflet/leaflet.js",
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
           "Select a county to zoom in and view its risk for this period.",
        )
        self.assertContains(
            response,
            "data-county-risk-card",
        )

    def test_dashboard_contains_period_control_contract(self):
        county = self.create_county(
            code="047",
            name="Nairobi",
        )
        self.create_prediction(
            county=county,
            observation_date=date(2025, 4, 30),
            risk_level=FloodPrediction.RiskLevel.HIGH,
        )

        self.client.force_login(self.user)

        response = self.client.get(
            reverse("monitoring-web:dashboard"),
            {
                "year": 2025,
                "month": 4,
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertContains(
            response,
            "Dashboard prediction period",
        )
        self.assertContains(
            response,
            'name="year"',
        )
        self.assertContains(
            response,
            'name="month"',
        )
        self.assertContains(
            response,
            "April 2025",
        )
        self.assertContains(
            response,
            "30 April 2025",
        )
        self.assertContains(
            response,
            "year=2025&amp;month=4",
        )
        self.assertContains(
            response,
            "latest flood-risk classification "
            "within the selected period",
        )

    def test_dashboard_accepts_year_with_all_months(self):
        county = self.create_county(
            code="047",
            name="Nairobi",
        )
        self.create_prediction(
            county=county,
            observation_date=date(2021, 12, 31),
            risk_level=FloodPrediction.RiskLevel.HIGH,
        )

        self.client.force_login(self.user)

        response = self.client.get(
            reverse("monitoring-web:dashboard"),
            {
                "year": "2021",
                "month": "",
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertContains(response, "2021")
        self.assertContains(
            response,
            "31 December 2021",
        )
        self.assertContains(
            response,
            "year=2021",
        )