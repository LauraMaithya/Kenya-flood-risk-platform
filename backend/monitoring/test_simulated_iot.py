from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from monitoring.models import (
    County,
    EnvironmentalObservation,
)
from monitoring.services.simulated_iot import (
    SimulatedIoTError,
    generate_simulated_iot_point,
)


class SimulatedIoTTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            slug="baringo",
            latitude=Decimal("0.676445"),
            longitude=Decimal("35.940327"),
            has_nasa_power_coverage=True,
        )
        self.recorded_at = timezone.make_aware(
            datetime(
                2026,
                10,
                23,
                12,
                0,
            )
        )

        self.create_observation(
            date(2010, 10, 5),
            precipitation="4.000",
            temperature="24.00",
            humidity="60.000",
            soil_wetness="0.300000",
        )
        self.create_observation(
            date(2015, 10, 15),
            precipitation="12.000",
            temperature="21.00",
            humidity="80.000",
            soil_wetness="0.700000",
        )

        self.create_observation(
            date(2026, 10, 5),
            precipitation="99.000",
            temperature="35.00",
            humidity="99.000",
            soil_wetness="0.990000",
        )

    def create_observation(
        self,
        observation_date,
        *,
        precipitation,
        temperature,
        humidity,
        soil_wetness,
        source=EnvironmentalObservation.Source.NASA_POWER,
        is_synthetic=False,
    ):
        return EnvironmentalObservation.objects.create(
            county=self.county,
            observation_date=observation_date,
            precipitation_max_mm=Decimal(
                precipitation
            ),
            temperature_mean_c=Decimal(
                temperature
            ),
            relative_humidity_mean_pct=Decimal(
                humidity
            ),
            soil_wetness_mean_fraction=Decimal(
                soil_wetness
            ),
            soil_wetness_max_fraction=Decimal(
                soil_wetness
            ),
            month_sin=Decimal("-1.00000000"),
            month_cos=Decimal("0.00000000"),
            source=source,
            source_record_id=(
                f"test-{observation_date}"
            ),
            is_synthetic=is_synthetic,
        )

    def test_point_uses_real_historical_county_month(self):
        point = generate_simulated_iot_point(
            self.county,
            recorded_at=self.recorded_at,
            seed="test-seed",
        )

        self.assertEqual(
            point.calibration_observation_count,
            2,
        )
        self.assertIn(
            point.calibration_reference_date,
            {
                date(2010, 10, 5),
                date(2015, 10, 15),
            },
        )
        self.assertIsNone(
            point.water_level_m
        )

    def test_generation_is_deterministic(self):
        first = generate_simulated_iot_point(
            self.county,
            recorded_at=self.recorded_at,
            seed="repeatable",
        )
        second = generate_simulated_iot_point(
            self.county,
            recorded_at=self.recorded_at,
            seed="repeatable",
        )

        self.assertEqual(
            first,
            second,
        )

    def test_generated_values_are_valid(self):
        point = generate_simulated_iot_point(
            self.county,
            recorded_at=self.recorded_at,
        )

        self.assertGreaterEqual(
            point.precipitation_mm,
            Decimal("0"),
        )
        self.assertGreaterEqual(
            point.relative_humidity_pct,
            Decimal("0"),
        )
        self.assertLessEqual(
            point.relative_humidity_pct,
            Decimal("100"),
        )
        self.assertGreaterEqual(
            point.soil_wetness_fraction,
            Decimal("0"),
        )
        self.assertLessEqual(
            point.soil_wetness_fraction,
            Decimal("1"),
        )
        self.assertGreaterEqual(
            point.battery_pct,
            Decimal("70"),
        )
        self.assertLessEqual(
            point.battery_pct,
            Decimal("100"),
        )

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaisesRegex(
            SimulatedIoTError,
            "must be timezone-aware",
        ):
            generate_simulated_iot_point(
                self.county,
                recorded_at=datetime(
                    2026,
                    10,
                    23,
                    12,
                    0,
                ),
            )

    def test_missing_historical_calibration_is_rejected(self):
        county = County.objects.create(
            code="001",
            name="Mombasa",
            slug="mombasa",
            latitude=Decimal("-4.043477"),
            longitude=Decimal("39.668206"),
            has_nasa_power_coverage=False,
        )

        with self.assertRaisesRegex(
            SimulatedIoTError,
            "No real historical NASA POWER observations",
        ):
            generate_simulated_iot_point(
                county,
                recorded_at=self.recorded_at,
            )