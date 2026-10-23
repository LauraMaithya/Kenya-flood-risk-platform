from datetime import date
from decimal import Decimal

from django.test import TestCase

from monitoring.models import (
    County,
    EnvironmentalObservation,
)
from monitoring.services.nasa_power_etl import (
    NasaPowerCountyDay,
)
from monitoring.services.nasa_power_storage import (
    NasaPowerStorageError,
    store_nasa_power_county_days,
)


class NasaPowerStorageTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            slug="baringo",
            latitude=Decimal("0.676445"),
            longitude=Decimal("35.940327"),
            has_nasa_power_coverage=True,
        )

    def build_county_day(self, **overrides):
        values = {
            "observation_date": date(2026, 1, 1),
            "precipitation_max_mm": Decimal("5.700"),
            "temperature_mean_c": Decimal("22.00"),
            "relative_humidity_mean_pct": Decimal("75.000"),
            "soil_wetness_mean_fraction": Decimal("0.500000"),
            "soil_wetness_max_fraction": Decimal("0.600000"),
            "month_sin": Decimal("0.00000000"),
            "month_cos": Decimal("1.00000000"),
            "contributing_points": 3,
        }
        values.update(overrides)

        return NasaPowerCountyDay(**values)

    def test_county_day_is_stored_as_real_nasa_observation(self):
        summary = store_nasa_power_county_days(
            self.county,
            [self.build_county_day()],
        )
        observation = EnvironmentalObservation.objects.get()

        self.assertEqual(summary.created, 1)
        self.assertEqual(summary.updated, 0)
        self.assertEqual(summary.unchanged, 0)
        self.assertEqual(
            observation.source,
            EnvironmentalObservation.Source.NASA_POWER,
        )
        self.assertFalse(observation.is_synthetic)
        self.assertEqual(
            observation.source_record_id,
            "NASA_POWER_030_20260101",
        )

    def test_repeated_identical_load_is_unchanged(self):
        county_day = self.build_county_day()

        store_nasa_power_county_days(
            self.county,
            [county_day],
        )
        summary = store_nasa_power_county_days(
            self.county,
            [county_day],
        )

        self.assertEqual(summary.created, 0)
        self.assertEqual(summary.updated, 0)
        self.assertEqual(summary.unchanged, 1)
        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            1,
        )

    def test_existing_nasa_observation_can_be_updated(self):
        store_nasa_power_county_days(
            self.county,
            [self.build_county_day()],
        )
        updated_day = self.build_county_day(
            precipitation_max_mm=Decimal("9.200"),
        )

        summary = store_nasa_power_county_days(
            self.county,
            [updated_day],
        )
        observation = EnvironmentalObservation.objects.get()

        self.assertEqual(summary.updated, 1)
        self.assertEqual(
            observation.precipitation_max_mm,
            Decimal("9.200"),
        )

    def test_other_source_is_not_overwritten(self):
        day = self.build_county_day()
        EnvironmentalObservation.objects.create(
            county=self.county,
            observation_date=day.observation_date,
            precipitation_max_mm=day.precipitation_max_mm,
            temperature_mean_c=day.temperature_mean_c,
            relative_humidity_mean_pct=(
                day.relative_humidity_mean_pct
            ),
            soil_wetness_mean_fraction=(
                day.soil_wetness_mean_fraction
            ),
            soil_wetness_max_fraction=(
                day.soil_wetness_max_fraction
            ),
            month_sin=day.month_sin,
            month_cos=day.month_cos,
            source=(
                EnvironmentalObservation.Source.MANUAL
            ),
            source_record_id="manual-test",
        )

        with self.assertRaisesRegex(
            NasaPowerStorageError,
            "cannot overwrite an observation",
        ):
            store_nasa_power_county_days(
                self.county,
                [day],
            )

    def test_dry_run_does_not_save_observation(self):
        summary = store_nasa_power_county_days(
            self.county,
            [self.build_county_day()],
            dry_run=True,
        )

        self.assertTrue(summary.dry_run)
        self.assertEqual(summary.created, 1)
        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            0,
        )

    def test_duplicate_input_dates_are_rejected(self):
        county_day = self.build_county_day()

        with self.assertRaisesRegex(
            NasaPowerStorageError,
            "contains duplicate dates",
        ):
            store_nasa_power_county_days(
                self.county,
                [county_day, county_day],
            )