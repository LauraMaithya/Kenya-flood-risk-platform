from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from monitoring.models import County
from monitoring.services.simulated_iot_refresh import (
    SimulatedIoTRefreshSummary,
)


class SimulatedIoTCommandTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            slug="baringo",
            latitude=Decimal("0.676445"),
            longitude=Decimal("35.940327"),
            has_nasa_power_coverage=True,
        )
        self.recorded_at = datetime(
            2026,
            10,
            23,
            15,
            0,
            tzinfo=timezone(
                timedelta(hours=3)
            ),
        )

    def summary(self, *, dry_run=False):
        return SimulatedIoTRefreshSummary(
            county_code="030",
            county_name="Baringo",
            recorded_at=self.recorded_at,
            calibration_observation_count=496,
            calibration_reference_date=date(
                2019,
                10,
                23,
            ),
            device_created=True,
            reading_created=True,
            reading_updated=False,
            device_id="SIMULATED-030-001",
            message_id=(
                "SIMULATED-030-20261023T120000Z"
            ),
            dry_run=dry_run,
        )

    @patch(
        "monitoring.management.commands."
        "simulate_iot."
        "refresh_simulated_iot_county"
    )
    def test_command_simulates_selected_county(
        self,
        refresh_mock,
    ):
        refresh_mock.return_value = self.summary()
        output = StringIO()

        call_command(
            "simulate_iot",
            county_code="030",
            recorded_at=(
                "2026-10-23T15:00:00+03:00"
            ),
            seed="command-test",
            stdout=output,
        )

        refresh_mock.assert_called_once_with(
            self.county,
            recorded_at=self.recorded_at,
            seed="command-test",
            dry_run=False,
        )
        self.assertIn(
            "030 Baringo",
            output.getvalue(),
        )
        self.assertIn(
            "496 historical observations",
            output.getvalue(),
        )
        self.assertIn(
            "Simulated IoT refresh COMPLETED",
            output.getvalue(),
        )

    @patch(
        "monitoring.management.commands."
        "simulate_iot."
        "refresh_simulated_iot_county"
    )
    def test_dry_run_is_forwarded(
        self,
        refresh_mock,
    ):
        refresh_mock.return_value = self.summary(
            dry_run=True
        )
        output = StringIO()

        call_command(
            "simulate_iot",
            county_code="030",
            recorded_at=(
                "2026-10-23T15:00:00+03:00"
            ),
            dry_run=True,
            stdout=output,
        )

        refresh_mock.assert_called_once_with(
            self.county,
            recorded_at=self.recorded_at,
            seed=None,
            dry_run=True,
        )
        self.assertIn(
            "Simulated IoT refresh DRY RUN",
            output.getvalue(),
        )

    def test_unknown_county_is_rejected(self):
        with self.assertRaisesRegex(
            CommandError,
            "Unknown county code",
        ):
            call_command(
                "simulate_iot",
                county_code="999",
                recorded_at=(
                    "2026-10-23T15:00:00+03:00"
                ),
            )

    def test_invalid_recorded_time_is_rejected(self):
        with self.assertRaisesRegex(
            CommandError,
            "Invalid recorded time",
        ):
            call_command(
                "simulate_iot",
                county_code="030",
                recorded_at="not-a-date",
            )

    def test_naive_recorded_time_is_rejected(self):
        with self.assertRaisesRegex(
            CommandError,
            "must include a timezone offset",
        ):
            call_command(
                "simulate_iot",
                county_code="030",
                recorded_at="2026-10-23T15:00:00",
            )