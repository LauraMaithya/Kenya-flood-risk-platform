from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from monitoring.models import County
from monitoring.services.simulated_iot import (
    SimulatedIoTError,
    SimulatedIoTPoint,
)
from monitoring.services.simulated_iot_refresh import (
    SimulatedIoTRefreshError,
    refresh_simulated_iot_county,
)
from monitoring.services.simulated_iot_storage import (
    SimulatedIoTStorageSummary,
)


class SimulatedIoTRefreshTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="030",
            name="Baringo",
            slug="baringo",
            latitude=Decimal("0.676445"),
            longitude=Decimal("35.940327"),
            has_nasa_power_coverage=True,
        )
        self.recorded_at = timezone.make_aware(
            datetime(
                2026,
                10,
                23,
                15,
                0,
            )
        )
        self.point = SimulatedIoTPoint(
            recorded_at=self.recorded_at,
            precipitation_mm=Decimal("3.500"),
            temperature_c=Decimal("23.50"),
            relative_humidity_pct=Decimal("68.000"),
            soil_wetness_fraction=Decimal("0.400000"),
            water_level_m=None,
            battery_pct=Decimal("90.000"),
            calibration_observation_count=496,
            calibration_reference_date=date(
                2019,
                10,
                23,
            ),
        )

    @patch(
        "monitoring.services.simulated_iot_refresh."
        "store_simulated_iot_point"
    )
    @patch(
        "monitoring.services.simulated_iot_refresh."
        "generate_simulated_iot_point"
    )
    def test_refresh_generates_and_stores_packet(
        self,
        generate_mock,
        storage_mock,
    ):
        generate_mock.return_value = self.point
        storage_mock.return_value = (
            SimulatedIoTStorageSummary(
                device_id="SIMULATED-030-001",
                message_id=(
                    "SIMULATED-030-20261023T120000Z"
                ),
                device_created=True,
                reading_created=True,
                reading_updated=False,
                dry_run=False,
            )
        )

        summary = refresh_simulated_iot_county(
            self.county,
            recorded_at=self.recorded_at,
            seed="test-seed",
        )

        generate_mock.assert_called_once_with(
            self.county,
            recorded_at=self.recorded_at,
            seed="test-seed",
        )
        storage_mock.assert_called_once_with(
            self.county,
            self.point,
            dry_run=False,
        )
        self.assertTrue(
            summary.device_created
        )
        self.assertTrue(
            summary.reading_created
        )
        self.assertEqual(
            summary.calibration_observation_count,
            496,
        )
        self.assertEqual(
            summary.calibration_reference_date,
            date(2019, 10, 23),
        )

    @patch(
        "monitoring.services.simulated_iot_refresh."
        "store_simulated_iot_point"
    )
    @patch(
        "monitoring.services.simulated_iot_refresh."
        "generate_simulated_iot_point"
    )
    def test_dry_run_is_forwarded_to_storage(
        self,
        generate_mock,
        storage_mock,
    ):
        generate_mock.return_value = self.point
        storage_mock.return_value = (
            SimulatedIoTStorageSummary(
                device_id="SIMULATED-030-001",
                message_id=(
                    "SIMULATED-030-20261023T120000Z"
                ),
                device_created=True,
                reading_created=True,
                reading_updated=False,
                dry_run=True,
            )
        )

        summary = refresh_simulated_iot_county(
            self.county,
            recorded_at=self.recorded_at,
            dry_run=True,
        )

        storage_mock.assert_called_once_with(
            self.county,
            self.point,
            dry_run=True,
        )
        self.assertTrue(
            summary.dry_run
        )

    @patch(
        "monitoring.services.simulated_iot_refresh."
        "generate_simulated_iot_point"
    )
    def test_generation_error_is_wrapped(
        self,
        generate_mock,
    ):
        generate_mock.side_effect = SimulatedIoTError(
            "No calibration data."
        )

        with self.assertRaisesRegex(
            SimulatedIoTRefreshError,
            "generation failed for Baringo",
        ):
            refresh_simulated_iot_county(
                self.county,
                recorded_at=self.recorded_at,
            )