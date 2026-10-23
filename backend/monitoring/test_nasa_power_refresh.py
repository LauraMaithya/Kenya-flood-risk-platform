from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from monitoring.models import (
    County,
    EnvironmentalObservation,
)
from monitoring.services.nasa_power import (
    NasaPowerDailyPoint,
)
from monitoring.services.nasa_power_refresh import (
    NasaPowerRefreshError,
    refresh_nasa_power_county,
)


class NasaPowerRefreshTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            slug="baringo",
            latitude=Decimal("0.676445"),
            longitude=Decimal("35.940327"),
            has_nasa_power_coverage=True,
        )
        self.observation_date = date(2026, 1, 1)

    def build_point_record(
        self,
        *,
        precipitation,
        temperature,
        humidity,
        soil_wetness,
    ):
        return NasaPowerDailyPoint(
            observation_date=self.observation_date,
            precipitation_mm=Decimal(
                precipitation
            ),
            temperature_c=Decimal(
                temperature
            ),
            relative_humidity_pct=Decimal(
                humidity
            ),
            soil_wetness_fraction=Decimal(
                soil_wetness
            ),
        )

    def sample_points(self):
        return {
            "baringo": {
                "county_name": "Baringo",
                "points": (
                    (35.8, 0.5),
                    (36.0, 0.7),
                    (35.9, 0.9),
                ),
            }
        }

    @patch(
        "monitoring.services.nasa_power_refresh."
        "fetch_nasa_power_daily_point"
    )
    @patch(
        "monitoring.services.nasa_power_refresh."
        "load_county_sample_points"
    )
    def test_refresh_extracts_transforms_and_loads(
        self,
        load_points,
        fetch_point,
    ):
        load_points.return_value = self.sample_points()
        fetch_point.side_effect = [
            [
                self.build_point_record(
                    precipitation="1.0",
                    temperature="20",
                    humidity="70",
                    soil_wetness="0.4",
                )
            ],
            [
                self.build_point_record(
                    precipitation="5.0",
                    temperature="22",
                    humidity="80",
                    soil_wetness="0.6",
                )
            ],
            [
                self.build_point_record(
                    precipitation="3.0",
                    temperature="24",
                    humidity="75",
                    soil_wetness="0.5",
                )
            ],
        ]

        summary = refresh_nasa_power_county(
            self.county,
            start_date=self.observation_date,
            end_date=self.observation_date,
        )
        observation = EnvironmentalObservation.objects.get()

        self.assertEqual(summary.requested_points, 3)
        self.assertEqual(summary.county_days, 1)
        self.assertEqual(summary.observations_created, 1)
        self.assertEqual(fetch_point.call_count, 3)
        self.assertEqual(
            observation.precipitation_max_mm,
            Decimal("5.000"),
        )
        self.assertEqual(
            observation.temperature_mean_c,
            Decimal("22.00"),
        )
        self.assertEqual(
            observation.soil_wetness_mean_fraction,
            Decimal("0.500000"),
        )
        self.assertEqual(
            observation.soil_wetness_max_fraction,
            Decimal("0.600000"),
        )

    @patch(
        "monitoring.services.nasa_power_refresh."
        "fetch_nasa_power_daily_point"
    )
    @patch(
        "monitoring.services.nasa_power_refresh."
        "load_county_sample_points"
    )
    def test_dry_run_does_not_store_observations(
        self,
        load_points,
        fetch_point,
    ):
        load_points.return_value = self.sample_points()
        record = self.build_point_record(
            precipitation="1",
            temperature="20",
            humidity="70",
            soil_wetness="0.4",
        )
        fetch_point.return_value = [record]

        summary = refresh_nasa_power_county(
            self.county,
            start_date=self.observation_date,
            end_date=self.observation_date,
            dry_run=True,
        )

        self.assertTrue(summary.dry_run)
        self.assertEqual(summary.observations_created, 1)
        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            0,
        )

    def test_county_without_nasa_coverage_is_rejected(self):
        self.county.has_nasa_power_coverage = False
        self.county.save(
            update_fields=[
                "has_nasa_power_coverage",
            ]
        )

        with self.assertRaisesRegex(
            NasaPowerRefreshError,
            "not marked for NASA POWER coverage",
        ):
            refresh_nasa_power_county(
                self.county,
                start_date=self.observation_date,
                end_date=self.observation_date,
            )

    @patch(
        "monitoring.services.nasa_power_refresh."
        "load_county_sample_points"
    )
    def test_missing_county_boundary_is_rejected(
        self,
        load_points,
    ):
        load_points.return_value = {}

        with self.assertRaisesRegex(
            NasaPowerRefreshError,
            "No county boundary matched",
        ):
            refresh_nasa_power_county(
                self.county,
                start_date=self.observation_date,
                end_date=self.observation_date,
            )