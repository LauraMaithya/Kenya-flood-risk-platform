from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.management import (
    CommandError,
    call_command,
)
from django.test import TestCase

from monitoring.models import County
from monitoring.services.nasa_power_refresh import (
    NasaPowerDataUnavailable,
    NasaPowerRefreshSummary,
)
from monitoring.services.nasa_power_prediction import (
    NasaPowerPredictionSummary,
)

class NasaPowerCommandTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            slug="baringo",
            latitude="0.676445",
            longitude="35.940327",
            has_nasa_power_coverage=True,
        )

    @patch(
        "monitoring.management.commands.refresh_nasa_power."
        "refresh_nasa_power_county"
    )
    def test_command_refreshes_only_missing_range(
        self,
        refresh_county,
    ):
        refresh_county.return_value = (
            NasaPowerRefreshSummary(
                county_code="030",
                county_name="Baringo",
                requested_points=3,
                county_days=3,
                observations_created=3,
                observations_updated=0,
                observations_unchanged=0,
                dry_run=True,
            )
        )
        output = StringIO()

        call_command(
            "refresh_nasa_power",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-01-03",
            "--county-code",
            "030",
            "--dry-run",
            stdout=output,
        )

        refresh_county.assert_called_once()
        call_kwargs = refresh_county.call_args.kwargs

        self.assertEqual(
            call_kwargs["start_date"],
            date(2026, 1, 1),
        )
        self.assertEqual(
            call_kwargs["end_date"],
            date(2026, 1, 3),
        )
        self.assertTrue(call_kwargs["dry_run"])
        self.assertIn(
            "NASA POWER refresh DRY RUN",
            output.getvalue(),
        )

    @patch(
        "monitoring.management.commands.refresh_nasa_power."
        "refresh_nasa_power_county"
    )
    def test_plan_only_makes_no_api_requests(
        self,
        refresh_county,
    ):
        output = StringIO()

        call_command(
            "refresh_nasa_power",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-01-03",
            "--county-code",
            "030",
            "--plan-only",
            stdout=output,
        )

        refresh_county.assert_not_called()
        self.assertIn(
            "3 missing county-days",
            output.getvalue(),
        )
        self.assertIn(
            "without API requests",
            output.getvalue(),
        )

    def test_invalid_date_format_is_rejected(self):
        with self.assertRaisesRegex(
            CommandError,
            "must use YYYY-MM-DD",
        ):
            call_command(
                "refresh_nasa_power",
                "--start-date",
                "01-01-2026",
                "--end-date",
                "2026-01-03",
            )

    def test_pre_2026_date_is_rejected(self):
        with self.assertRaisesRegex(
            CommandError,
            "from 2026 onward",
        ):
            call_command(
                "refresh_nasa_power",
                "--start-date",
                "2025-12-31",
                "--end-date",
                "2026-01-03",
            )

    def test_unknown_county_code_is_rejected(self):
        with self.assertRaisesRegex(
            CommandError,
            "No matching NASA-covered counties",
        ):
            call_command(
                "refresh_nasa_power",
                "--start-date",
                "2026-01-01",
                "--end-date",
                "2026-01-03",
                "--county-code",
                "999",
            )

    def test_invalid_sample_point_count_is_rejected(self):
        with self.assertRaisesRegex(
            CommandError,
            "--sample-points must be greater than zero",
        ):
            call_command(
                "refresh_nasa_power",
                "--start-date",
                "2026-01-01",
                "--end-date",
                "2026-01-03",
                "--sample-points",
                "0",
            )
    @patch(
        "monitoring.management.commands.refresh_nasa_power."
        "refresh_nasa_power_county"
    )
    def test_unpublished_range_is_deferred(
        self,
        refresh_county,
    ):
        refresh_county.side_effect = (
            NasaPowerDataUnavailable(
                "NASA POWER data is not yet available."
            )
        )
        output = StringIO()

        call_command(
            "refresh_nasa_power",
            "--start-date",
            "2026-10-21",
            "--end-date",
            "2026-10-22",
            "--county-code",
            "030",
            stdout=output,
        )

        self.assertIn(
            "Deferred:",
            output.getvalue(),
        )
        self.assertIn(
            "1 ranges deferred containing 2 county-days",
            output.getvalue(),
        )
    @patch(
        "monitoring.management.commands.refresh_nasa_power."
        "predict_missing_nasa_power"
    )
    @patch(
        "monitoring.management.commands.refresh_nasa_power."
        "refresh_nasa_power_county"
    )
    def test_refresh_automatically_predicts_observations(
        self,
        refresh_county,
        predict_missing,
    ):
        refresh_county.return_value = (
            NasaPowerRefreshSummary(
                county_code="030",
                county_name="Baringo",
                requested_points=3,
                county_days=3,
                observations_created=3,
                observations_updated=0,
                observations_unchanged=0,
                dry_run=False,
            )
        )
        predict_missing.return_value = (
            NasaPowerPredictionSummary(
                observations_found=3,
                predictions_pending=3,
                predictions_created=3,
                predictions_existing=0,
                batches_processed=1,
            )
        )
        output = StringIO()

        call_command(
            "refresh_nasa_power",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-01-03",
            "--county-code",
            "030",
            "--prediction-batch-size",
            "50",
            stdout=output,
        )

        predict_missing.assert_called_once()

        call_kwargs = predict_missing.call_args.kwargs

        self.assertEqual(
            call_kwargs["start_date"],
            date(2026, 1, 1),
        )
        self.assertEqual(
            call_kwargs["end_date"],
            date(2026, 1, 3),
        )
        self.assertEqual(
            call_kwargs["batch_size"],
            50,
        )
        self.assertIn(
            "3 created",
            output.getvalue(),
        )
    def test_invalid_prediction_batch_size_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            CommandError,
            "--prediction-batch-size must be greater than zero",
        ):
            call_command(
                "refresh_nasa_power",
                "--start-date",
                "2026-01-01",
                "--end-date",
                "2026-01-03",
                "--prediction-batch-size",
                "0",
            )