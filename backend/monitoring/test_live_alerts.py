from datetime import date
from decimal import Decimal

from django.test import TestCase

from monitoring.models import (
    AlertNotification,
    County,
    EnvironmentalObservation,
    FloodPrediction,
)
from monitoring.services.live_alerts import (
    LiveAlertError,
    create_live_high_risk_alerts,
)


class LiveAlertTests(TestCase):
    def setUp(self):
        self.observation_date = date(
            2026,
            10,
            23,
        )

        live_county = self.create_county(
            "030",
            "Baringo",
        )
        nasa_county = self.create_county(
            "040",
            "Busia",
        )
        simulated_county = self.create_county(
            "028",
            "Elgeyo-Marakwet",
        )
        low_county = self.create_county(
            "014",
            "Embu",
        )

        self.live_high_prediction = self.create_prediction(
            live_county,
            source=(
                EnvironmentalObservation.Source.LIVE_API_IOT
            ),
            is_synthetic=False,
            risk_level=FloodPrediction.RiskLevel.HIGH,
            record_id="live-high",
        )
        self.create_prediction(
            nasa_county,
            source=(
                EnvironmentalObservation.Source.NASA_POWER
            ),
            is_synthetic=False,
            risk_level=FloodPrediction.RiskLevel.HIGH,
            record_id="nasa-high",
        )
        self.create_prediction(
            simulated_county,
            source=(
                EnvironmentalObservation.Source.SIMULATED_IOT
            ),
            is_synthetic=True,
            risk_level=FloodPrediction.RiskLevel.HIGH,
            record_id="simulated-high",
        )
        self.create_prediction(
            low_county,
            source=(
                EnvironmentalObservation.Source.LIVE_API_IOT
            ),
            is_synthetic=False,
            risk_level=FloodPrediction.RiskLevel.LOW,
            record_id="live-low",
        )

    def create_county(
        self,
        code,
        name,
    ):
        return County.objects.create(
            code=code,
            name=name,
            slug=name.lower().replace(
                " ",
                "-",
            ),
            latitude=Decimal("0.500000"),
            longitude=Decimal("36.000000"),
            has_nasa_power_coverage=True,
        )

    def create_prediction(
        self,
        county,
        *,
        source,
        is_synthetic,
        risk_level,
        record_id,
    ):
        observation = (
            EnvironmentalObservation.objects.create(
                county=county,
                observation_date=self.observation_date,
                precipitation_max_mm=Decimal("20.000"),
                temperature_mean_c=Decimal("24.00"),
                relative_humidity_mean_pct=Decimal("70.000"),
                soil_wetness_mean_fraction=Decimal(
                    "0.500000"
                ),
                soil_wetness_max_fraction=Decimal(
                    "0.600000"
                ),
                month_sin=Decimal("-1.00000000"),
                month_cos=Decimal("0.00000000"),
                source=source,
                source_record_id=record_id,
                is_synthetic=is_synthetic,
            )
        )

        if risk_level == FloodPrediction.RiskLevel.HIGH:
            probabilities = {
                "probability_low": Decimal("0.100000"),
                "probability_medium": Decimal("0.200000"),
                "probability_high": Decimal("0.700000"),
            }
        else:
            probabilities = {
                "probability_low": Decimal("0.700000"),
                "probability_medium": Decimal("0.200000"),
                "probability_high": Decimal("0.100000"),
            }

        return FloodPrediction.objects.create(
            observation=observation,
            risk_level=risk_level,
            model_release_id=(
                "kenya_flood_risk_rf_v1_0_0"
            ),
            decision_rule="HIGH_THRESHOLD_0.44",
            high_probability_threshold=Decimal(
                "0.440000"
            ),
            **probabilities,
        )

    def test_only_real_live_high_prediction_is_alerted(self):
        summary = create_live_high_risk_alerts(
            self.observation_date,
            channel="IN_APP",
            recipient="dashboard",
        )

        self.assertEqual(
            summary.high_risk_predictions,
            1,
        )
        self.assertEqual(
            summary.alerts_created,
            1,
        )
        self.assertEqual(
            summary.alerts_existing,
            0,
        )
        self.assertEqual(
            AlertNotification.objects.count(),
            1,
        )
        self.assertEqual(
            AlertNotification.objects.get().prediction,
            self.live_high_prediction,
        )

    def test_alert_options_are_optional(self):
        summary = create_live_high_risk_alerts(
            self.observation_date
        )

        self.assertEqual(
            summary.high_risk_predictions,
            1,
        )
        self.assertEqual(
            summary.alerts_created,
            0,
        )
        self.assertEqual(
            AlertNotification.objects.count(),
            0,
        )

    def test_alert_options_must_be_together(self):
        with self.assertRaisesRegex(
            LiveAlertError,
            "must be provided together",
        ):
            create_live_high_risk_alerts(
                self.observation_date,
                channel="IN_APP",
            )

    def test_repeated_alert_creation_is_idempotent(self):
        first = create_live_high_risk_alerts(
            self.observation_date,
            channel="IN_APP",
            recipient="dashboard",
        )
        second = create_live_high_risk_alerts(
            self.observation_date,
            channel="IN_APP",
            recipient="dashboard",
        )

        self.assertEqual(
            first.alerts_created,
            1,
        )
        self.assertEqual(
            second.alerts_created,
            0,
        )
        self.assertEqual(
            second.alerts_existing,
            1,
        )
        self.assertEqual(
            AlertNotification.objects.count(),
            1,
        )