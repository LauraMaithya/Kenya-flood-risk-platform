import csv
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from monitoring.models import County, EnvironmentalObservation
from monitoring.services.observation_ingestion import (
    ObservationIngestionError,
    ingest_observations,
)


class ObservationIngestionTests(TestCase):
    def setUp(self):
        self.temporary_files = []

        self.valid_row = {
            "county_code": "047",
            "county_name": "Nairobi",
            "latitude": "-1.286389",
            "longitude": "36.817223",
            "observation_date": "2026-01-15",
            "precipitation_max_mm": "42.5",
            "temperature_mean_c": "24.8",
            "relative_humidity_mean_pct": "71.2",
            "soil_wetness_mean_fraction": "0.48",
            "soil_wetness_max_fraction": "0.63",
            "source_record_id": "test-047-2026-01-15",
            "quality_review_required": "false",
        }

    def tearDown(self):
        for path in self.temporary_files:
            path.unlink(missing_ok=True)

    def write_csv(self, rows, fieldnames=None):
        if fieldnames is None:
            fieldnames = list(rows[0].keys())

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
                fieldnames=fieldnames,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)

        path = Path(temporary_file.name)
        self.temporary_files.append(path)
        return path

    def test_ingestion_creates_county_and_observation(self):
        csv_path = self.write_csv([self.valid_row])

        summary = ingest_observations(csv_path)

        self.assertEqual(summary.processed, 1)
        self.assertEqual(summary.created, 1)
        self.assertEqual(summary.updated, 0)
        self.assertEqual(summary.counties_created, 1)

        county = County.objects.get(code="047")
        observation = EnvironmentalObservation.objects.get(
            county=county,
            observation_date="2026-01-15",
        )

        self.assertEqual(county.name, "Nairobi")
        self.assertEqual(
            float(observation.precipitation_max_mm),
            42.5,
        )
        self.assertAlmostEqual(
            float(observation.month_sin),
            0.5,
            places=6,
        )
        self.assertAlmostEqual(
            float(observation.month_cos),
            0.8660254,
            places=6,
        )
        self.assertFalse(observation.is_synthetic)

    def test_reimport_updates_existing_observation(self):
        csv_path = self.write_csv([self.valid_row])
        ingest_observations(csv_path)

        updated_row = self.valid_row.copy()
        updated_row["precipitation_max_mm"] = "55.75"
        updated_csv_path = self.write_csv([updated_row])

        summary = ingest_observations(updated_csv_path)

        self.assertEqual(summary.created, 0)
        self.assertEqual(summary.updated, 1)
        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            1,
        )

        observation = EnvironmentalObservation.objects.get()
        self.assertEqual(
            float(observation.precipitation_max_mm),
            55.75,
        )

    def test_dry_run_does_not_save_records(self):
        csv_path = self.write_csv([self.valid_row])

        summary = ingest_observations(csv_path, dry_run=True)

        self.assertTrue(summary.dry_run)
        self.assertEqual(summary.processed, 1)
        self.assertEqual(County.objects.count(), 0)
        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            0,
        )

    def test_missing_required_column_is_rejected(self):
        missing_column = "soil_wetness_max_fraction"
        fieldnames = [
            column
            for column in self.valid_row
            if column != missing_column
        ]
        csv_path = self.write_csv(
            [self.valid_row],
            fieldnames=fieldnames,
        )

        with self.assertRaisesRegex(
            ObservationIngestionError,
            missing_column,
        ):
            ingest_observations(csv_path)

    def test_management_command_imports_csv(self):
        csv_path = self.write_csv([self.valid_row])
        output = StringIO()

        call_command(
            "import_observations",
            "--file",
            str(csv_path),
            stdout=output,
        )

        self.assertIn("1 processed", output.getvalue())
        self.assertEqual(
            EnvironmentalObservation.objects.count(),
            1,
        )