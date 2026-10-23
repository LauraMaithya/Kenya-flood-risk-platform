from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from monitoring.models import County
from monitoring.services.open_meteo_refresh import (
    OpenMeteoRefreshSummary,
)


class OpenMeteoCommandTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            latitude="0.676445",
            longitude="35.940327",
        )

    @patch(
        "monitoring.management.commands."
        "refresh_open_meteo."
        "refresh_open_meteo_county"
    )
    def test_command_refreshes_selected_county(
        self,
        refresh_mock,
    ):
        refresh_mock.return_value = (
            OpenMeteoRefreshSummary(
                county_code="030",
                county_name="Baringo",
                observation_date=date(
                    2026,
                    10,
                    23,
                ),
                device_created=True,
                reading_created=True,
                reading_updated=False,
                observation_created=True,
                observation_updated=False,
                observation_preserved=False,
                prediction_created=True,
                prediction_existing=False,
                dry_run=False,
            )
        )
        output = StringIO()

        call_command(
            "refresh_open_meteo",
            county_code="030",
            observation_date="2026-10-23",
            timeout=60,
            stdout=output,
        )

        refresh_mock.assert_called_once_with(
            self.county,
            observation_date=date(
                2026,
                10,
                23,
            ),
            timeout=60,
            dry_run=False,
        )
        self.assertIn(
            "030 Baringo",
            output.getvalue(),
        )
        self.assertIn(
            "1 predictions created",
            output.getvalue(),
        )
        self.assertIn(
            "Open-Meteo refresh COMPLETED",
            output.getvalue(),
        )

    @patch(
        "monitoring.management.commands."
        "refresh_open_meteo."
        "refresh_open_meteo_county"
    )
    def test_dry_run_is_forwarded_to_service(
        self,
        refresh_mock,
    ):
        refresh_mock.return_value = (
            OpenMeteoRefreshSummary(
                county_code="030",
                county_name="Baringo",
                observation_date=date(
                    2026,
                    10,
                    23,
                ),
                device_created=True,
                reading_created=True,
                reading_updated=False,
                observation_created=True,
                observation_updated=False,
                observation_preserved=False,
                prediction_created=False,
                prediction_existing=False,
                dry_run=True,
            )
        )
        output = StringIO()

        call_command(
            "refresh_open_meteo",
            county_code="030",
            observation_date="2026-10-23",
            dry_run=True,
            stdout=output,
        )

        refresh_mock.assert_called_once_with(
            self.county,
            observation_date=date(
                2026,
                10,
                23,
            ),
            timeout=30,
            dry_run=True,
        )
        self.assertIn(
            "Open-Meteo refresh DRY RUN",
            output.getvalue(),
        )

    def test_unknown_county_code_is_rejected(self):
        with self.assertRaisesRegex(
            CommandError,
            "Unknown county code",
        ):
            call_command(
                "refresh_open_meteo",
                county_code="999",
                observation_date="2026-10-23",
            )

    def test_invalid_date_is_rejected(self):
        with self.assertRaisesRegex(
            CommandError,
            "Invalid date",
        ):
            call_command(
                "refresh_open_meteo",
                county_code="030",
                observation_date="23-10-2026",
            )

    def test_nonpositive_timeout_is_rejected(self):
        with self.assertRaisesRegex(
            CommandError,
            "timeout must be greater than zero",
        ):
            call_command(
                "refresh_open_meteo",
                county_code="030",
                observation_date="2026-10-23",
                timeout=0,
            )