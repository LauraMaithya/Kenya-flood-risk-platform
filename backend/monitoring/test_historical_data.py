import csv
import io
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


class HistoricalDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="history-user",
            email="history@example.com",
            password=PASSWORD,
        )

        cls.nairobi = cls.create_county(
            code="047",
            name="Nairobi",
        )
        cls.mombasa = cls.create_county(
            code="001",
            name="Mombasa",
        )
        cls.kwale = cls.create_county(
            code="002",
            name="Kwale",
        )

        cls.create_prediction(
            county=cls.nairobi,
            observation_date=date(2025, 1, 10),
            risk_level=FloodPrediction.RiskLevel.HIGH,
        )
        cls.create_prediction(
            county=cls.mombasa,
            observation_date=date(2025, 2, 10),
            risk_level=FloodPrediction.RiskLevel.MEDIUM,
        )
        cls.create_prediction(
            county=cls.kwale,
            observation_date=date(2025, 3, 10),
            risk_level=FloodPrediction.RiskLevel.LOW,
        )
        cls.create_prediction(
            county=cls.nairobi,
            observation_date=date(2025, 1, 11),
            risk_level=FloodPrediction.RiskLevel.LOW,
            is_synthetic=True,
        )

    @classmethod
    def create_county(cls, *, code, name):
        return County.objects.create(
            code=code,
            name=name,
            slug=name.lower().replace(" ", "-"),
            latitude=Decimal("-1.000000"),
            longitude=Decimal("37.000000"),
            has_nasa_power_coverage=True,
        )

    @classmethod
    def create_prediction(
        cls,
        *,
        county,
        observation_date,
        risk_level,
        is_synthetic=False,
        model_release_id="kenya_flood_risk_rf_v1_0_0",
    ):
        observation = (
            EnvironmentalObservation.objects.create(
                county=county,
                observation_date=observation_date,
                precipitation_max_mm=Decimal("25.000"),
                temperature_mean_c=Decimal("24.00"),
                relative_humidity_mean_pct=Decimal("70.000"),
                soil_wetness_mean_fraction=Decimal(
                    "0.400000"
                ),
                soil_wetness_max_fraction=Decimal(
                    "0.600000"
                ),
                month_sin=Decimal("0.50000000"),
                month_cos=Decimal("0.86602540"),
                is_synthetic=is_synthetic,
            )
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
            high_probability_threshold=Decimal(
                "0.440000"
            ),
        )

    def setUp(self):
        self.page_url = reverse(
            "monitoring-web:historical-data"
        )
        self.download_url = reverse(
            "monitoring-web:historical-data-download"
        )

    def authenticate(self):
        self.client.force_login(self.user)

    def test_page_and_download_require_authentication(self):
        page_response = self.client.get(self.page_url)
        download_response = self.client.get(
            self.download_url
        )

        self.assertEqual(page_response.status_code, 302)
        self.assertEqual(download_response.status_code, 302)
        self.assertIn(
            reverse("monitoring-web:login"),
            page_response.url,
        )
        self.assertIn(
            reverse("monitoring-web:login"),
            download_response.url,
        )

    def test_default_results_exclude_synthetic_records(self):
        self.authenticate()

        response = self.client.get(self.page_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "monitoring/historical_data.html",
        )
        self.assertEqual(
            response.context["result_count"],
            3,
        )
        self.assertNotContains(
            response,
            "2025-01-11",
        )

    def test_county_filter_returns_matching_records(self):
        self.authenticate()

        response = self.client.get(
            self.page_url,
            {"county": "nairobi"},
        )

        predictions = list(
            response.context["predictions"]
        )

        self.assertEqual(
            response.context["result_count"],
            1,
        )
        self.assertEqual(
            predictions[0].observation.county,
            self.nairobi,
        )
        self.assertEqual(
            predictions[0].risk_level,
            FloodPrediction.RiskLevel.HIGH,
        )

    def test_risk_and_date_filters_are_applied(self):
        self.authenticate()

        response = self.client.get(
            self.page_url,
            {
                "risk_level": (
                    FloodPrediction.RiskLevel.MEDIUM
                ),
                "start_date": "2025-02-01",
                "end_date": "2025-02-28",
            },
        )

        predictions = list(
            response.context["predictions"]
        )

        self.assertEqual(
            response.context["result_count"],
            1,
        )
        self.assertEqual(
            predictions[0].observation.county,
            self.mombasa,
        )

    def test_reversed_date_range_is_rejected(self):
        self.authenticate()

        response = self.client.get(
            self.page_url,
            {
                "start_date": "2025-03-01",
                "end_date": "2025-02-01",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["result_count"],
            0,
        )
        self.assertContains(
            response,
            "Start date must be on or before end date.",
        )

    def test_results_are_paginated_at_25_records(self):
        base_date = date(2024, 1, 1)

        for offset in range(25):
            self.create_prediction(
                county=self.nairobi,
                observation_date=(
                    base_date + timedelta(days=offset)
                ),
                risk_level=(
                    FloodPrediction.RiskLevel.LOW
                ),
                model_release_id=f"pagination-{offset}",
            )

        self.authenticate()
        response = self.client.get(self.page_url)

        self.assertEqual(
            response.context["result_count"],
            28,
        )
        self.assertEqual(
            len(response.context["predictions"]),
            25,
        )
        self.assertEqual(
            response.context["page_obj"].paginator.num_pages,
            2,
        )

    def test_csv_uses_filters_and_excludes_synthetic_data(self):
        self.authenticate()

        response = self.client.get(
            self.download_url,
            {"county": "nairobi"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "text/csv",
        )
        self.assertIn(
            "kenya_flood_risk_history.csv",
            response["Content-Disposition"],
        )

        csv_text = response.content.decode("utf-8")
        rows = list(
            csv.DictReader(io.StringIO(csv_text))
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["county_name"],
            "Nairobi",
        )
        self.assertEqual(
            rows[0]["observation_date"],
            "2025-01-10",
        )
        self.assertEqual(
            rows[0]["risk_level"],
            "High",
        )

    def test_invalid_csv_filters_return_bad_request(self):
        self.authenticate()

        response = self.client.get(
            self.download_url,
            {
                "start_date": "2025-03-01",
                "end_date": "2025-02-01",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.content,
            b"Invalid historical-data filters.",
        )

    def test_year_filter_applies_to_page_and_download(self):
        self.create_prediction(
            county=self.nairobi,
            observation_date=date(2024, 6, 15),
            risk_level=FloodPrediction.RiskLevel.HIGH,
            model_release_id="historical-2024",
        )

        self.authenticate()

        page_response = self.client.get(
            self.page_url,
            {"year": "2025"},
        )

        self.assertEqual(
            page_response.status_code,
            200,
        )
        self.assertEqual(
            page_response.context["result_count"],
            3,
        )

        page_predictions = list(
            page_response.context["predictions"]
        )

        self.assertTrue(
            all(
                prediction.observation.observation_date.year
                == 2025
                for prediction in page_predictions
            )
        )

        year_choices = dict(
            page_response.context[
                "filter_form"
            ].fields["year"].choices
        )

        self.assertIn("2025", year_choices)
        self.assertIn("2024", year_choices)

        download_response = self.client.get(
            self.download_url,
            {"year": "2025"},
        )

        csv_text = download_response.content.decode(
            "utf-8"
        )
        rows = list(
            csv.DictReader(
                io.StringIO(csv_text)
            )
        )

        self.assertEqual(len(rows), 3)
        self.assertTrue(
            all(
                row["observation_date"].startswith(
                    "2025-"
                )
                for row in rows
            )
        )

    def test_coverage_summary_uses_active_filters(self):
        self.authenticate()

        response = self.client.get(
            self.page_url,
            {"county": "nairobi"},
        )

        summary = response.context[
            "coverage_summary"
        ]

        self.assertEqual(
            summary["total_records"],
            1,
        )
        self.assertEqual(
            summary["counties_covered"],
            1,
        )
        self.assertEqual(
            summary["first_date"],
            date(2025, 1, 10),
        )
        self.assertEqual(
            summary["last_date"],
            date(2025, 1, 10),
        )
        self.assertEqual(
            summary["high_count"],
            1,
        )
        self.assertEqual(
            summary["medium_count"],
            0,
        )
        self.assertEqual(
            summary["low_count"],
            0,
        )
        self.assertEqual(
            summary["high_percentage"],
            100.0,
        )
        self.assertContains(
            response,
            "Stored historical classifications",
        )
        self.assertContains(
            response,
            "not a new model",
        )
        self.assertContains(
            response,
            "accuracy evaluation",
        )