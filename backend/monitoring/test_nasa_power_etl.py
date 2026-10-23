from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from monitoring.services.nasa_power import (
    NasaPowerDailyPoint,
)
from monitoring.services.nasa_power_etl import (
    NasaPowerETLError,
    aggregate_nasa_power_points,
)


class NasaPowerETLTests(SimpleTestCase):
    def build_record(
        self,
        *,
        observation_date,
        precipitation,
        temperature,
        humidity,
        soil_wetness,
    ):
        return NasaPowerDailyPoint(
            observation_date=observation_date,
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

    def test_points_are_aggregated_into_county_day(self):
        observation_date = date(2026, 1, 1)
        first_point = [
            self.build_record(
                observation_date=observation_date,
                precipitation="1.200",
                temperature="20.00",
                humidity="70.000",
                soil_wetness="0.400000",
            )
        ]
        second_point = [
            self.build_record(
                observation_date=observation_date,
                precipitation="5.700",
                temperature="24.00",
                humidity="80.000",
                soil_wetness="0.600000",
            )
        ]

        results = aggregate_nasa_power_points(
            [first_point, second_point]
        )
        result = results[0]

        self.assertEqual(len(results), 1)
        self.assertEqual(
            result.precipitation_max_mm,
            Decimal("5.700"),
        )
        self.assertEqual(
            result.temperature_mean_c,
            Decimal("22.00"),
        )
        self.assertEqual(
            result.relative_humidity_mean_pct,
            Decimal("75.000"),
        )
        self.assertEqual(
            result.soil_wetness_mean_fraction,
            Decimal("0.500000"),
        )
        self.assertEqual(
            result.soil_wetness_max_fraction,
            Decimal("0.600000"),
        )
        self.assertEqual(result.month_sin, Decimal("0E-8"))
        self.assertEqual(
            result.month_cos,
            Decimal("1.00000000"),
        )
        self.assertEqual(result.contributing_points, 2)

    def test_february_uses_historical_seasonal_encoding(self):
        record = self.build_record(
            observation_date=date(2026, 2, 1),
            precipitation="0",
            temperature="23",
            humidity="60",
            soil_wetness="0.5",
        )

        result = aggregate_nasa_power_points(
            [[record]]
        )[0]

        self.assertEqual(
            result.month_sin,
            Decimal("0.50000000"),
        )
        self.assertEqual(
            result.month_cos,
            Decimal("0.86602540"),
        )

    def test_only_dates_available_at_every_point_are_used(self):
        first_date = date(2026, 1, 1)
        second_date = date(2026, 1, 2)
        shared = self.build_record(
            observation_date=first_date,
            precipitation="1",
            temperature="20",
            humidity="70",
            soil_wetness="0.4",
        )
        unshared = self.build_record(
            observation_date=second_date,
            precipitation="2",
            temperature="21",
            humidity="71",
            soil_wetness="0.5",
        )

        results = aggregate_nasa_power_points(
            [
                [shared, unshared],
                [shared],
            ]
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].observation_date,
            first_date,
        )

    def test_duplicate_point_date_is_rejected(self):
        record = self.build_record(
            observation_date=date(2026, 1, 1),
            precipitation="1",
            temperature="20",
            humidity="70",
            soil_wetness="0.4",
        )

        with self.assertRaisesRegex(
            NasaPowerETLError,
            "contains duplicate date",
        ):
            aggregate_nasa_power_points(
                [[record, record]]
            )

    def test_empty_point_collection_is_rejected(self):
        with self.assertRaisesRegex(
            NasaPowerETLError,
            "At least one NASA POWER point",
        ):
            aggregate_nasa_power_points([])

    def test_point_without_records_is_rejected(self):
        with self.assertRaisesRegex(
            NasaPowerETLError,
            "has no records",
        ):
            aggregate_nasa_power_points([[]])

    def test_points_without_common_dates_are_rejected(self):
        first = self.build_record(
            observation_date=date(2026, 1, 1),
            precipitation="1",
            temperature="20",
            humidity="70",
            soil_wetness="0.4",
        )
        second = self.build_record(
            observation_date=date(2026, 1, 2),
            precipitation="2",
            temperature="21",
            humidity="71",
            soil_wetness="0.5",
        )

        with self.assertRaisesRegex(
            NasaPowerETLError,
            "no common complete dates",
        ):
            aggregate_nasa_power_points(
                [[first], [second]]
            )