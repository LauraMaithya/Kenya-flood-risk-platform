from datetime import date
from decimal import Decimal

from django.test import TestCase

from monitoring.models import (
    County,
    EnvironmentalObservation,
)
from monitoring.services.nasa_power_schedule import (
    NasaPowerScheduleError,
    build_nasa_power_refresh_plan,
    find_missing_nasa_power_ranges,
)


class NasaPowerScheduleTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            slug="baringo",
            latitude=Decimal("0.676445"),
            longitude=Decimal("35.940327"),
            has_nasa_power_coverage=True,
        )

    def create_observation(
        self,
        observation_date,
        *,
        source=EnvironmentalObservation.Source.NASA_POWER,
    ):
        return EnvironmentalObservation.objects.create(
            county=self.county,
            observation_date=observation_date,
            precipitation_max_mm=Decimal("1.000"),
            temperature_mean_c=Decimal("22.00"),
            relative_humidity_mean_pct=Decimal("70.000"),
            soil_wetness_mean_fraction=Decimal("0.400000"),
            soil_wetness_max_fraction=Decimal("0.500000"),
            month_sin=Decimal("0.00000000"),
            month_cos=Decimal("1.00000000"),
            source=source,
            source_record_id=(
                f"test-{observation_date}"
            ),
            is_synthetic=False,
        )

    def test_existing_prefix_advances_missing_start(self):
        self.create_observation(date(2026, 1, 1))
        self.create_observation(date(2026, 1, 2))
        self.create_observation(date(2026, 1, 3))

        ranges = find_missing_nasa_power_ranges(
            self.county,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 10),
        )

        self.assertEqual(len(ranges), 1)
        self.assertEqual(
            ranges[0].start_date,
            date(2026, 1, 4),
        )
        self.assertEqual(
            ranges[0].end_date,
            date(2026, 1, 10),
        )
        self.assertEqual(ranges[0].day_count, 7)

    def test_internal_gaps_become_separate_ranges(self):
        self.create_observation(date(2026, 1, 1))
        self.create_observation(date(2026, 1, 3))
        self.create_observation(date(2026, 1, 5))

        ranges = find_missing_nasa_power_ranges(
            self.county,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 5),
        )

        self.assertEqual(len(ranges), 2)
        self.assertEqual(
            (
                ranges[0].start_date,
                ranges[0].end_date,
            ),
            (
                date(2026, 1, 2),
                date(2026, 1, 2),
            ),
        )
        self.assertEqual(
            (
                ranges[1].start_date,
                ranges[1].end_date,
            ),
            (
                date(2026, 1, 4),
                date(2026, 1, 4),
            ),
        )

    def test_complete_period_has_no_missing_ranges(self):
        for day in range(1, 4):
            self.create_observation(
                date(2026, 1, day)
            )

        ranges = find_missing_nasa_power_ranges(
            self.county,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
        )

        self.assertEqual(ranges, ())

    def test_live_api_observation_is_covered(self):
        self.create_observation(
            date(2026, 1, 1),
        )
        self.create_observation(
            date(2026, 1, 2),
            source=(
                EnvironmentalObservation.Source.LIVE_API_IOT
            ),
        )
        self.create_observation(
            date(2026, 1, 3),
        )

        ranges = find_missing_nasa_power_ranges(
            self.county,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
        )

        self.assertEqual(ranges, ())

    def test_protected_source_conflict_is_rejected(self):
        protected_sources = (
            EnvironmentalObservation.Source.MANUAL,
            EnvironmentalObservation.Source.IMPORTED,
        )

        for source in protected_sources:
            with self.subTest(source=source):
                observation = self.create_observation(
                    date(2026, 1, 2),
                    source=source,
                )

                with self.assertRaisesRegex(
                    NasaPowerScheduleError,
                    f"found an existing {source} observation",
                ):
                    find_missing_nasa_power_ranges(
                        self.county,
                        start_date=date(2026, 1, 1),
                        end_date=date(2026, 1, 3),
                    )

                observation.delete()

    def test_multiple_counties_are_included_in_plan(self):
        second_county = County.objects.create(
            code="040",
            name="Busia",
            slug="busia",
            latitude=Decimal("0.389952"),
            longitude=Decimal("34.193812"),
            has_nasa_power_coverage=True,
        )

        plan = build_nasa_power_refresh_plan(
            [self.county, second_county],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
        )

        self.assertEqual(len(plan), 2)
        self.assertEqual(
            {
                item.county_code
                for item in plan
            },
            {"030", "040"},
        )
        self.assertEqual(
            sum(item.day_count for item in plan),
            4,
        )

    def test_invalid_date_range_is_rejected(self):
        with self.assertRaisesRegex(
            NasaPowerScheduleError,
            "start date must be on or before end date",
        ):
            find_missing_nasa_power_ranges(
                self.county,
                start_date=date(2026, 2, 1),
                end_date=date(2026, 1, 1),
            )