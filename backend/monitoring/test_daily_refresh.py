import csv
import tempfile
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import (
    call_command,
    CommandError,
)
from django.test import TestCase

from monitoring.models import (
    AlertNotification,
    County,
    EnvironmentalObservation,
    FloodPrediction,
)
from monitoring.services.prediction_service import (
    PredictionResult,
)


RELEASE_ID = "kenya_flood_risk_rf_v1_0_0"

STORAGE_RELEASE_PATCH = (
    "monitoring.services.prediction_storage."
    "get_model_release"
)

DAILY_RELEASE_PATCH = (
    "monitoring.services.daily_refresh."
    "get_model_release"
)

BATCH_PREDICTION_PATCH = (
    "monitoring.services.prediction_storage."
    "predict_observations"
)


class DailyRefreshTests(TestCase):
    def setUp(self):
        self.temporary_files = []

        self.valid_row = {
            "county_code": "047",
            "county_name": "Nairobi",
            "latitude": "-1.286389",
            "longitude": "36.817223",
            "observation_date": "2026-01-15",
            "precipitation_max_mm": "42.500",
            "temperature_mean_c": "24.80",
            "relative_humidity_mean_pct": "71.200",
            "soil_wetness_mean_fraction": "0.480000",
            "soil_wetness_max_fraction": "0.630000",
            "source": "NASA_POWER",
            "source_record_id": "daily-047-2026-01-15",
            "quality_review_required": "false",
        }

        self.release = SimpleNamespace(
            release_id=RELEASE_ID,
        )

        self.model_result = PredictionResult(
            risk_level="High",
            probability_low=0.10,
            probability_medium=0.20,
            probability_high=0.70,
            model_release_id=RELEASE_ID,
            model_version="1.0.0",
            high_threshold=0.44,
        )

    def tearDown(self):
        for path in self.temporary_files:
            path.unlink(missing_ok=True)

    def write_csv(self, rows):
        temporary_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            encoding="utf-8",
            newline="",
            delete=False,
        )

        with temporary_file:
            writer = csv.DictWriter(
                temporary_file,
                fieldnames=list(rows[0].keys()),
            )
            writer.writeheader()
            writer.writerows(rows)

        path = Path(temporary_file.name)
        self.temporary_files.append(path)

        return path

    def run_refresh_command(
        self,
        csv_path,
        *,
        alert_channel=None,
        alert_recipient=None,
    ):
        command_arguments = [
            "daily_refresh",
            "--file",
            str(csv_path),
            "--batch-size",
            "2",
        ]

        if alert_channel is not None:
            command_arguments.extend(
                [
                    "--alert-channel",
                    alert_channel,
                ]
            )

        if alert_recipient is not None:
            command_arguments.extend(
                [
                    "--alert-recipient",
                    alert_recipient,
                ]
            )

        output = StringIO()

        def prediction_results(observations):
            return tuple(
                self.model_result
                for _observation in observations
            )

        with (
            patch(
                STORAGE_RELEASE_PATCH,
                return_value=self.release,
            ),
            patch(
                DAILY_RELEASE_PATCH,
                return_value=self.release,
            ),
            patch(
                BATCH_PREDICTION_PATCH,
                side_effect=prediction_results,
            ),
        ):
            call_command(
                *command_arguments,
                stdout=output,
            )

        return output.getvalue()

    def test_refresh_ingests_and_predicts(self):
        csv_path = self.write_csv(
            [self.valid_row]
        )

        output = self.run_refresh_command(
            csv_path
        )

        self.assertEqual(
            County.objects.count(),
            1,
        )
        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            1,
        )
        self.assertEqual(
            FloodPrediction.objects.count(),
            1,
        )
        self.assertEqual(
            AlertNotification.objects.count(),
            0,
        )

        prediction = FloodPrediction.objects.get()

        self.assertEqual(
            prediction.risk_level,
            "High",
        )
        self.assertEqual(
            prediction.model_release_id,
            RELEASE_ID,
        )
        self.assertIn(
            "1 observations processed",
            output,
        )
        self.assertIn(
            "1 predictions created",
            output,
        )

    def test_refresh_optionally_creates_high_risk_alert(self):
        csv_path = self.write_csv(
            [self.valid_row]
        )

        output = self.run_refresh_command(
            csv_path,
            alert_channel="IN_APP",
            alert_recipient="dashboard",
        )

        self.assertEqual(
            AlertNotification.objects.count(),
            1,
        )

        alert = AlertNotification.objects.get()

        self.assertEqual(
            alert.status,
            "PENDING",
        )
        self.assertEqual(
            alert.channel,
            "IN_APP",
        )
        self.assertEqual(
            alert.recipient,
            "dashboard",
        )
        self.assertIn(
            "Nairobi",
            alert.message,
        )
        self.assertIn(
            "1 alerts created",
            output,
        )

    def test_repeated_refresh_is_idempotent(self):
        csv_path = self.write_csv(
            [self.valid_row]
        )

        self.run_refresh_command(
            csv_path,
            alert_channel="IN_APP",
            alert_recipient="dashboard",
        )

        second_output = self.run_refresh_command(
            csv_path,
            alert_channel="IN_APP",
            alert_recipient="dashboard",
        )

        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            1,
        )
        self.assertEqual(
            FloodPrediction.objects.count(),
            1,
        )
        self.assertEqual(
            AlertNotification.objects.count(),
            1,
        )
        self.assertIn(
            "0 predictions created",
            second_output,
        )
        self.assertIn(
            "1 existing",
            second_output,
        )

    def test_dry_run_rolls_back_without_prediction(self):
        csv_path = self.write_csv(
            [self.valid_row]
        )
        output = StringIO()

        call_command(
            "daily_refresh",
            "--file",
            str(csv_path),
            "--dry-run",
            stdout=output,
        )

        self.assertEqual(
            County.objects.count(),
            0,
        )
        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            0,
        )
        self.assertEqual(
            FloodPrediction.objects.count(),
            0,
        )
        self.assertEqual(
            AlertNotification.objects.count(),
            0,
        )
        self.assertIn(
            "DRY RUN completed",
            output.getvalue(),
        )

    def test_alert_options_must_be_provided_together(self):
        csv_path = self.write_csv(
            [self.valid_row]
        )

        with self.assertRaisesRegex(
            CommandError,
            "must be provided together",
        ):
            call_command(
                "daily_refresh",
                "--file",
                str(csv_path),
                "--alert-channel",
                "IN_APP",
            )

        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            0,
        )

    def test_alert_failure_rolls_back_refresh(self):
        csv_path = self.write_csv(
            [self.valid_row]
        )

        with self.assertRaisesRegex(
            CommandError,
            "valid email",
        ):
            self.run_refresh_command(
                csv_path,
                alert_channel="EMAIL",
                alert_recipient="not-an-email",
            )

        self.assertEqual(
            County.objects.count(),
            0,
        )
        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            0,
        )
        self.assertEqual(
            FloodPrediction.objects.count(),
            0,
        )
        self.assertEqual(
            AlertNotification.objects.count(),
            0,
        )