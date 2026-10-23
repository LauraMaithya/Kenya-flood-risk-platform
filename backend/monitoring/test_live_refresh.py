from datetime import date, datetime, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.test.utils import override_settings

from monitoring.services.live_alerts import (
    LiveAlertSummary,
)


@override_settings(TIME_ZONE="Africa/Nairobi")
class LiveRefreshCommandTests(SimpleTestCase):
    def setUp(self):
        self.output = StringIO()
        self.run_date = date(2026, 10, 23)
        self.recorded_at = datetime(
            2026,
            10,
            23,
            20,
            0,
            tzinfo=dt_timezone.utc,
        )

    @patch(
        "monitoring.management.commands.live_refresh."
        "create_live_high_risk_alerts"
    )
    @patch(
        "monitoring.management.commands.live_refresh."
        "call_command"
    )
    def test_complete_pipeline_runs_in_order(
        self,
        mocked_call_command,
        mocked_create_alerts,
    ):
        mocked_create_alerts.return_value = (
            LiveAlertSummary(
                observation_date=self.run_date,
                high_risk_predictions=2,
                alerts_created=2,
                alerts_existing=0,
            )
        )

        call_command(
            "live_refresh",
            observation_date=(
                self.run_date.isoformat()
            ),
            recorded_at=(
                self.recorded_at.isoformat()
            ),
            county_code="030",
            sample_points=3,
            timeout=60,
            prediction_batch_size=500,
            simulation_seed="test-seed",
            alert_channel="EMAIL",
            alert_recipient="alerts@example.com",
            stdout=self.output,
        )

        self.assertEqual(
            mocked_call_command.call_count,
            3,
        )

        expected_commands = [
            (
                "refresh_nasa_power",
                {
                    "end_date": "2026-10-22",
                    "county_code": "030",
                    "sample_points": 3,
                    "timeout": 60,
                    "prediction_batch_size": 500,
                    "dry_run": False,
                },
            ),
            (
                "refresh_open_meteo",
                {
                    "observation_date": "2026-10-23",
                    "county_code": "030",
                    "timeout": 60,
                    "dry_run": False,
                },
            ),
            (
                "simulate_iot",
                {
                    "recorded_at": (
                        "2026-10-23T20:00:00+00:00"
                    ),
                    "county_code": "030",
                    "seed": "test-seed",
                    "dry_run": False,
                },
            ),
        ]

        for actual_call, expected in zip(
            mocked_call_command.call_args_list,
            expected_commands,
        ):
            expected_name, expected_options = expected

            self.assertEqual(
                actual_call.args,
                (expected_name,),
            )

            for option_name, expected_value in (
                expected_options.items()
            ):
                self.assertEqual(
                    actual_call.kwargs[option_name],
                    expected_value,
                )

            self.assertIn(
                "stdout",
                actual_call.kwargs,
            )
            self.assertIn(
                "stderr",
                actual_call.kwargs,
            )

        mocked_create_alerts.assert_called_once_with(
            self.run_date,
            channel="EMAIL",
            recipient="alerts@example.com",
        )

        self.assertIn(
            "Live refresh COMPLETED",
            self.output.getvalue(),
        )

    @patch(
        "monitoring.management.commands.live_refresh."
        "create_live_high_risk_alerts"
    )
    @patch(
        "monitoring.management.commands.live_refresh."
        "call_command"
    )
    def test_dry_run_skips_alert_creation(
        self,
        mocked_call_command,
        mocked_create_alerts,
    ):
        call_command(
            "live_refresh",
            observation_date=(
                self.run_date.isoformat()
            ),
            recorded_at=(
                self.recorded_at.isoformat()
            ),
            county_code="030",
            dry_run=True,
            stdout=self.output,
        )

        self.assertEqual(
            mocked_call_command.call_count,
            3,
        )

        for command_call in (
            mocked_call_command.call_args_list
        ):
            self.assertTrue(
                command_call.kwargs["dry_run"]
            )

        mocked_create_alerts.assert_not_called()

        self.assertIn(
            "Alert creation skipped during dry run.",
            self.output.getvalue(),
        )
        self.assertIn(
            "Live refresh DRY RUN",
            self.output.getvalue(),
        )

    @patch(
        "monitoring.management.commands.live_refresh."
        "call_command"
    )
    def test_alert_options_must_be_together(
        self,
        mocked_call_command,
    ):
        with self.assertRaisesRegex(
            CommandError,
            "must be supplied together",
        ):
            call_command(
                "live_refresh",
                observation_date=(
                    self.run_date.isoformat()
                ),
                recorded_at=(
                    self.recorded_at.isoformat()
                ),
                alert_channel="EMAIL",
                stdout=self.output,
            )

        mocked_call_command.assert_not_called()

    @patch(
        "monitoring.management.commands.live_refresh."
        "call_command"
    )
    def test_invalid_sample_point_count_is_rejected(
        self,
        mocked_call_command,
    ):
        with self.assertRaisesRegex(
            CommandError,
            "sample-points must be greater than zero",
        ):
            call_command(
                "live_refresh",
                observation_date=(
                    self.run_date.isoformat()
                ),
                recorded_at=(
                    self.recorded_at.isoformat()
                ),
                sample_points=0,
                stdout=self.output,
            )

        mocked_call_command.assert_not_called()

    def test_naive_recorded_time_is_rejected(self):
        with self.assertRaisesRegex(
            CommandError,
            "must include a timezone offset",
        ):
            call_command(
                "live_refresh",
                observation_date=(
                    self.run_date.isoformat()
                ),
                recorded_at="2026-10-23T20:00:00",
                stdout=self.output,
            )

    def test_future_observation_date_is_rejected(self):
        with patch(
            "monitoring.management.commands.live_refresh."
            "timezone.localdate",
            return_value=date(2026, 10, 23),
        ):
            with self.assertRaisesRegex(
                CommandError,
                "cannot be in the future",
            ):
                call_command(
                    "live_refresh",
                    observation_date="2026-10-24",
                    recorded_at=(
                        self.recorded_at.isoformat()
                    ),
                    stdout=self.output,
                )