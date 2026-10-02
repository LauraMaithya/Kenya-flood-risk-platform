from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .models import (
    AlertNotification,
    County,
    EnvironmentalObservation,
    FloodPrediction,
)


class MonitoringModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.county = County.objects.create(
            code="030",
            name="Nairobi",
            slug="nairobi",
            latitude=Decimal("-1.286389"),
            longitude=Decimal("36.817223"),
            has_nasa_power_coverage=True,
        )

        cls.observation = EnvironmentalObservation.objects.create(
            county=cls.county,
            observation_date=date(2026, 10, 2),
            precipitation_max_mm=Decimal("25.500"),
            temperature_mean_c=Decimal("24.50"),
            relative_humidity_mean_pct=Decimal("76.250"),
            soil_wetness_mean_fraction=Decimal("0.410000"),
            soil_wetness_max_fraction=Decimal("0.620000"),
            month_sin=Decimal("-0.86602540"),
            month_cos=Decimal("0.50000000"),
            source=EnvironmentalObservation.Source.NASA_POWER,
            is_synthetic=False,
        )

    def valid_prediction(self, **overrides):
        values = {
            "observation": self.observation,
            "risk_level": FloodPrediction.RiskLevel.HIGH,
            "probability_low": Decimal("0.100000"),
            "probability_medium": Decimal("0.300000"),
            "probability_high": Decimal("0.600000"),
            "model_release_id": "kenya_flood_risk_rf_v1_0_0",
            "decision_rule": "HIGH_THRESHOLD_0.44",
            "high_probability_threshold": Decimal("0.440000"),
        }
        values.update(overrides)
        return FloodPrediction(**values)

    def test_county_is_created(self):
        self.assertEqual(str(self.county), "Nairobi")
        self.assertEqual(self.county.code, "030")
        self.assertTrue(self.county.has_nasa_power_coverage)

    def test_observation_stores_final_predictors(self):
        self.assertEqual(
            self.observation.precipitation_max_mm,
            Decimal("25.500"),
        )
        self.assertEqual(
            self.observation.soil_wetness_max_fraction,
            Decimal("0.620000"),
        )
        self.assertFalse(self.observation.is_synthetic)
        self.assertEqual(
            str(self.observation),
            "Nairobi — 2026-10-02",
        )

    def test_county_date_observation_must_be_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EnvironmentalObservation.objects.create(
                    county=self.county,
                    observation_date=date(2026, 10, 2),
                    precipitation_max_mm=Decimal("30.000"),
                    temperature_mean_c=Decimal("25.00"),
                    relative_humidity_mean_pct=Decimal("70.000"),
                    soil_wetness_mean_fraction=Decimal("0.400000"),
                    soil_wetness_max_fraction=Decimal("0.600000"),
                    month_sin=Decimal("-0.86602540"),
                    month_cos=Decimal("0.50000000"),
                )

    def test_invalid_observation_values_are_rejected(self):
        observation = EnvironmentalObservation(
            county=self.county,
            observation_date=date(2026, 10, 3),
            precipitation_max_mm=Decimal("-1.000"),
            temperature_mean_c=Decimal("24.00"),
            relative_humidity_mean_pct=Decimal("120.000"),
            soil_wetness_mean_fraction=Decimal("0.800000"),
            soil_wetness_max_fraction=Decimal("0.500000"),
            month_sin=Decimal("2.00000000"),
            month_cos=Decimal("0.50000000"),
        )

        with self.assertRaises(ValidationError):
            observation.full_clean()

    def test_valid_prediction_passes_validation(self):
        prediction = self.valid_prediction()
        prediction.full_clean()
        prediction.save()

        self.assertEqual(prediction.county, self.county)
        self.assertEqual(prediction.risk_level, "High")
        self.assertEqual(
            prediction.high_probability_threshold,
            Decimal("0.440000"),
        )

    def test_prediction_probabilities_must_sum_to_one(self):
        prediction = self.valid_prediction(
            probability_low=Decimal("0.200000"),
            probability_medium=Decimal("0.300000"),
            probability_high=Decimal("0.600000"),
        )

        with self.assertRaises(ValidationError):
            prediction.full_clean()

    def test_invalid_risk_level_is_rejected(self):
        prediction = self.valid_prediction(risk_level="Critical")

        with self.assertRaises(ValidationError):
            prediction.full_clean()

    def test_observation_model_release_must_be_unique(self):
        first_prediction = self.valid_prediction()
        first_prediction.full_clean()
        first_prediction.save()

        duplicate_prediction = self.valid_prediction()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate_prediction.save()

    def test_sent_alert_requires_sent_timestamp(self):
        prediction = self.valid_prediction()
        prediction.full_clean()
        prediction.save()

        alert = AlertNotification(
            prediction=prediction,
            channel=AlertNotification.Channel.IN_APP,
            message="High flood risk detected for Nairobi.",
            status=AlertNotification.Status.SENT,
            sent_at=None,
        )

        with self.assertRaises(ValidationError):
            alert.full_clean()

    def test_valid_sent_alert_is_saved(self):
        prediction = self.valid_prediction()
        prediction.full_clean()
        prediction.save()

        alert = AlertNotification(
            prediction=prediction,
            channel=AlertNotification.Channel.IN_APP,
            message="High flood risk detected for Nairobi.",
            status=AlertNotification.Status.SENT,
            sent_at=timezone.now(),
        )
        alert.full_clean()
        alert.save()

        self.assertEqual(alert.status, AlertNotification.Status.SENT)
        self.assertEqual(alert.prediction, prediction)