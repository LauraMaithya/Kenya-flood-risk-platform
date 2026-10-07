from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from monitoring.models import (
    County,
    EnvironmentalObservation,
    FloodPrediction,
)


User = get_user_model()
PASSWORD = "M7!qZ9#vR2@kL8$x"


class CountyRiskPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="county-risk-user",
            email="county-risk@example.com",
            password=PASSWORD,
        )

    def setUp(self):
        self.url = reverse("monitoring-web:county-risk")

    def authenticate(self):
        self.client.force_login(self.user)

    def create_county(self, *, code, name):
        return County.objects.create(
            code=code,
            name=name,
            slug=name.lower().replace(" ", "-"),
            latitude=Decimal("-1.000000"),
            longitude=Decimal("37.000000"),
            has_nasa_power_coverage=True,
        )

    def create_prediction(
        self,
        *,
        county,
        observation_date,
        risk_level=FloodPrediction.RiskLevel.HIGH,
        is_synthetic=False,
        model_release_id="kenya_flood_risk_rf_v1_0_0",
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

    def test_page_requires_authentication(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse("monitoring-web:login"),
            response.url,
        )

    def test_no_counties_state_is_rendered(self):
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "monitoring/county_risk.html",
        )
        self.assertContains(response, "No counties available")
        self.assertEqual(response.context["county_count"], 0)

    def test_page_prompts_for_county_selection(self):
        self.create_county(
            code="047",
            name="Nairobi",
        )
        self.authenticate()

        response = self.client.get(self.url)

        self.assertContains(response, "Select a county")
        self.assertIsNone(
            response.context["selected_county"]
        )
        self.assertIsNone(
            response.context["latest_prediction"]
        )

    def test_county_without_prediction_has_honest_state(self):
        county = self.create_county(
            code="001",
            name="Mombasa",
        )
        self.authenticate()

        response = self.client.get(
            self.url,
            {"county": county.slug},
        )

        self.assertEqual(
            response.context["selected_county"],
            county,
        )
        self.assertIsNone(
            response.context["latest_prediction"]
        )
        self.assertContains(
            response,
            "No current prediction",
        )

    def test_latest_real_prediction_is_selected(self):
        county = self.create_county(
            code="047",
            name="Nairobi",
        )
        older = self.create_prediction(
            county=county,
            observation_date=date(2025, 1, 1),
            risk_level=FloodPrediction.RiskLevel.LOW,
        )
        latest_real = self.create_prediction(
            county=county,
            observation_date=date(2025, 2, 1),
            risk_level=FloodPrediction.RiskLevel.HIGH,
        )
        self.create_prediction(
            county=county,
            observation_date=date(2025, 3, 1),
            risk_level=FloodPrediction.RiskLevel.MEDIUM,
            is_synthetic=True,
        )
        self.authenticate()

        response = self.client.get(
            self.url,
            {"county": county.slug},
        )

        self.assertNotEqual(
            response.context["latest_prediction"],
            older,
        )
        self.assertEqual(
            response.context["latest_prediction"],
            latest_real,
        )
        self.assertEqual(
            response.context["latest_prediction"].risk_level,
            FloodPrediction.RiskLevel.HIGH,
        )

    def test_latest_environmental_inputs_are_displayed(self):
        county = self.create_county(
            code="032",
            name="Nakuru",
        )
        prediction = self.create_prediction(
            county=county,
            observation_date=date(2025, 4, 1),
        )
        self.authenticate()

        response = self.client.get(
            self.url,
            {"county": county.slug},
        )

        self.assertEqual(
            response.context["latest_observation"],
            prediction.observation,
        )
        self.assertContains(
            response,
            "Maximum precipitation",
        )
        self.assertContains(
            response,
            "Mean temperature",
        )
        self.assertContains(
            response,
            "Mean relative humidity",
        )
        self.assertContains(
            response,
            "Mean soil wetness",
        )
        self.assertContains(
            response,
            "Maximum soil wetness",
        )
        self.assertContains(
            response,
            "Seasonal month sine",
        )
        self.assertContains(
            response,
            "Seasonal month cosine",
        )

    def test_recent_history_is_limited_to_ten_real_results(self):
        county = self.create_county(
            code="022",
            name="Kiambu",
        )
        starting_date = date(2025, 1, 1)

        for offset in range(12):
            self.create_prediction(
                county=county,
                observation_date=(
                    starting_date + timedelta(days=offset)
                ),
                model_release_id=f"release-{offset}",
            )

        self.create_prediction(
            county=county,
            observation_date=date(2025, 2, 1),
            is_synthetic=True,
            model_release_id="synthetic-release",
        )
        self.authenticate()

        response = self.client.get(
            self.url,
            {"county": county.slug},
        )

        recent = list(
            response.context["recent_predictions"]
        )

        self.assertEqual(len(recent), 10)
        self.assertEqual(
            recent[0].observation.observation_date,
            date(2025, 1, 12),
        )
        self.assertNotContains(
            response,
            "synthetic-release",
        )