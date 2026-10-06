from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from monitoring.models import (
    County,
    EnvironmentalObservation,
    FloodPrediction,
)


User = get_user_model()
PASSWORD = "M7!qZ9#vR2@kL8$x"


@override_settings(ALLOWED_HOSTS=["testserver"])
class DashboardPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="dashboard-user",
            email="dashboard@example.com",
            password=PASSWORD,
        )

    def create_prediction(
        self,
        *,
        county_code,
        county_name,
        observation_date,
        risk_level,
    ):
        county, _ = County.objects.get_or_create(
            code=county_code,
            defaults={
                "name": county_name,
                "slug": county_name.lower().replace(" ", "-"),
                "latitude": Decimal("-1.000000"),
                "longitude": Decimal("37.000000"),
                "has_nasa_power_coverage": True,
            },
        )

        observation = EnvironmentalObservation.objects.create(
            county=county,
            observation_date=observation_date,
            precipitation_max_mm=Decimal("20.000"),
            temperature_mean_c=Decimal("24.00"),
            relative_humidity_mean_pct=Decimal("70.000"),
            soil_wetness_mean_fraction=Decimal("0.400000"),
            soil_wetness_max_fraction=Decimal("0.600000"),
            month_sin=Decimal("0.50000000"),
            month_cos=Decimal("0.86602540"),
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
            model_release_id="kenya_flood_risk_rf_v1_0_0",
            decision_rule="HIGH_THRESHOLD_0.44",
            high_probability_threshold=Decimal("0.440000"),
        )

    def test_login_page_is_available_anonymously(self):
        response = self.client.get(
            reverse("monitoring-web:login")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "monitoring/login.html",
        )

    def test_registration_page_is_available_anonymously(self):
        response = self.client.get(
            reverse("monitoring-web:register")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "monitoring/register.html",
        )

    def test_anonymous_root_redirects_to_login(self):
        response = self.client.get(
            reverse("monitoring-web:root")
        )

        self.assertRedirects(
            response,
            reverse("monitoring-web:login"),
            fetch_redirect_response=False,
        )

    def test_authenticated_root_redirects_to_dashboard(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("monitoring-web:root")
        )

        self.assertRedirects(
            response,
            reverse("monitoring-web:dashboard"),
            fetch_redirect_response=False,
        )

    def test_anonymous_dashboard_access_redirects_to_login(self):
        dashboard_url = reverse(
            "monitoring-web:dashboard"
        )

        response = self.client.get(dashboard_url)

        expected_url = (
            f"{reverse('monitoring-web:login')}"
            f"?next={dashboard_url}"
        )

        self.assertRedirects(
            response,
            expected_url,
            fetch_redirect_response=False,
        )

    def test_authenticated_user_can_access_dashboard(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("monitoring-web:dashboard")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "monitoring/dashboard.html",
        )
        self.assertContains(
            response,
            "National flood-risk overview",
        )

    def test_dashboard_shows_zero_counts_without_predictions(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("monitoring-web:dashboard")
        )

        self.assertEqual(
            response.context["high_risk_count"],
            0,
        )
        self.assertEqual(
            response.context["medium_risk_count"],
            0,
        )
        self.assertEqual(
            response.context["low_risk_count"],
            0,
        )
        self.assertEqual(
            response.context["monitored_count"],
            0,
        )
        self.assertIsNone(
            response.context["latest_data_date"]
        )

    def test_dashboard_counts_latest_prediction_per_county(self):
        self.create_prediction(
            county_code="001",
            county_name="Mombasa",
            observation_date=date(2026, 9, 1),
            risk_level=FloodPrediction.RiskLevel.HIGH,
        )
        self.create_prediction(
            county_code="001",
            county_name="Mombasa",
            observation_date=date(2026, 10, 1),
            risk_level=FloodPrediction.RiskLevel.LOW,
        )
        self.create_prediction(
            county_code="047",
            county_name="Nairobi",
            observation_date=date(2026, 10, 2),
            risk_level=FloodPrediction.RiskLevel.HIGH,
        )
        self.create_prediction(
            county_code="022",
            county_name="Kiambu",
            observation_date=date(2026, 10, 3),
            risk_level=FloodPrediction.RiskLevel.MEDIUM,
        )

        self.client.force_login(self.user)

        response = self.client.get(
            reverse("monitoring-web:dashboard")
        )

        self.assertEqual(
            response.context["high_risk_count"],
            1,
        )
        self.assertEqual(
            response.context["medium_risk_count"],
            1,
        )
        self.assertEqual(
            response.context["low_risk_count"],
            1,
        )
        self.assertEqual(
            response.context["monitored_count"],
            3,
        )
        self.assertEqual(
            response.context["latest_data_date"],
            date(2026, 10, 3),
        )

    def test_placeholder_pages_require_authentication(self):
        protected_routes = (
            "monitoring-web:county-risk",
            "monitoring-web:historical-data",
            "monitoring-web:alerts",
            "monitoring-web:profile",
        )

        for route_name in protected_routes:
            with self.subTest(route=route_name):
                response = self.client.get(
                    reverse(route_name)
                )

                self.assertEqual(response.status_code, 302)
                self.assertTrue(
                    response.url.startswith(
                        reverse("monitoring-web:login")
                    )
                )

    def test_authenticated_user_can_access_placeholder_pages(self):
        self.client.force_login(self.user)

        protected_routes = (
            "monitoring-web:county-risk",
            "monitoring-web:historical-data",
            "monitoring-web:alerts",
            "monitoring-web:profile",
        )

        for route_name in protected_routes:
            with self.subTest(route=route_name):
                response = self.client.get(
                    reverse(route_name)
                )

                self.assertEqual(response.status_code, 200)

    def test_existing_authentication_api_routes_remain_resolvable(self):
        expected_paths = {
            "monitoring-api:auth-csrf": "/api/auth/csrf/",
            "monitoring-api:auth-register": "/api/auth/register/",
            "monitoring-api:auth-login": "/api/auth/login/",
            "monitoring-api:auth-logout": "/api/auth/logout/",
            "monitoring-api:auth-me": "/api/auth/me/",
        }

        for route_name, expected_path in expected_paths.items():
            with self.subTest(route=route_name):
                self.assertEqual(
                    reverse(route_name),
                    expected_path,
                )