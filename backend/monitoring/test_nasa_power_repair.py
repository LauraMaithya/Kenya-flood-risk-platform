from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from monitoring.models import County, EnvironmentalObservation


class NasaPowerPrecipitationRepairTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            slug="baringo",
        )

    def observation(self, *, source, precipitation, day):
        return EnvironmentalObservation.objects.create(
            county=self.county,
            observation_date=date(2026, 10, day),
            precipitation_max_mm=Decimal(precipitation),
            temperature_mean_c=Decimal("24.00"),
            relative_humidity_mean_pct=Decimal("70.000"),
            soil_wetness_mean_fraction=Decimal("0.300000"),
            soil_wetness_max_fraction=Decimal("0.400000"),
            month_sin=Decimal("-0.86602540"),
            month_cos=Decimal("0.50000000"),
            source=source,
            source_record_id=f"SOURCE_030_202610{day:02d}",
            is_synthetic=False,
        )

    @patch(
        "monitoring.management.commands."
        "repair_nasa_power_precipitation.refresh_prediction_batch"
    )
    def test_repairs_nasa_once_and_preserves_live_rows(self, refresh_predictions):
        refresh_predictions.return_value.processed = 1
        refresh_predictions.return_value.updated = 1
        refresh_predictions.return_value.created = 0
        nasa = self.observation(
            source=EnvironmentalObservation.Source.NASA_POWER,
            precipitation="426.480",
            day=10,
        )
        live = self.observation(
            source=EnvironmentalObservation.Source.LIVE_API_IOT,
            precipitation="2.900",
            day=11,
        )

        with TemporaryDirectory() as temporary:
            backup = Path(temporary) / "backup.csv"
            call_command(
                "repair_nasa_power_precipitation",
                start_date="2026-10-01",
                end_date="2026-10-31",
                confirm=True,
                backup=backup,
                verbosity=0,
            )
            self.assertTrue(backup.is_file())
        nasa.refresh_from_db()
        live.refresh_from_db()

        self.assertEqual(nasa.precipitation_max_mm, Decimal("17.770"))
        self.assertTrue(
            nasa.source_record_id.endswith("|PRECIP_MM_DAY_FIX_V1")
        )
        self.assertEqual(live.precipitation_max_mm, Decimal("2.900"))
        refresh_predictions.assert_called_once()
        refreshed_rows = refresh_predictions.call_args.args[0]
        self.assertEqual([row.pk for row in refreshed_rows], [nasa.pk])

        call_command(
            "repair_nasa_power_precipitation",
            start_date="2026-10-01",
            end_date="2026-10-31",
            confirm=True,
            verbosity=0,
        )
        nasa.refresh_from_db()
        self.assertEqual(nasa.precipitation_max_mm, Decimal("17.770"))
        self.assertEqual(refresh_predictions.call_count, 1)

    @patch(
        "monitoring.management.commands."
        "repair_nasa_power_precipitation.refresh_prediction_batch"
    )
    def test_audit_does_not_change_rows(self, refresh_predictions):
        nasa = self.observation(
            source=EnvironmentalObservation.Source.NASA_POWER,
            precipitation="240.000",
            day=12,
        )

        call_command(
            "repair_nasa_power_precipitation",
            start_date="2026-10-01",
            end_date="2026-10-31",
            verbosity=0,
        )
        nasa.refresh_from_db()

        self.assertEqual(nasa.precipitation_max_mm, Decimal("240.000"))
        refresh_predictions.assert_not_called()
