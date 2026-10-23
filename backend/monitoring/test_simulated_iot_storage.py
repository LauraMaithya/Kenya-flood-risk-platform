from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from monitoring.models import (
    County,
    SensorDevice,
    SensorReading,
)
from monitoring.services.simulated_iot import (
    SimulatedIoTPoint,
)
from monitoring.services.simulated_iot_storage import (
    SimulatedIoTStorageError,
    store_simulated_iot_point,
)


class SimulatedIoTStorageTests(TestCase):
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
                14,
                30,
            )
        )
        self.point = SimulatedIoTPoint(
            recorded_at=self.recorded_at,
            precipitation_mm=Decimal("4.250"),
            temperature_c=Decimal("24.50"),
            relative_humidity_pct=Decimal("72.500"),
            soil_wetness_fraction=Decimal("0.450000"),
            water_level_m=None,
            battery_pct=Decimal("91.500"),
            calibration_observation_count=496,
            calibration_reference_date=date(
                2018,
                10,
                12,
            ),
        )

    def test_point_creates_simulated_device_and_reading(self):
        summary = store_simulated_iot_point(
            self.county,
            self.point,
        )

        self.assertTrue(
            summary.device_created
        )
        self.assertTrue(
            summary.reading_created
        )
        self.assertFalse(
            summary.reading_updated
        )

        device = SensorDevice.objects.get(
            device_id="SIMULATED-030-001"
        )
        reading = SensorReading.objects.get(
            message_id=summary.message_id
        )

        self.assertEqual(
            device.data_origin,
            SensorDevice.DataOrigin.SIMULATED,
        )
        self.assertTrue(
            device.is_simulated
        )
        self.assertEqual(
            reading.upstream_provider,
            SensorReading.UpstreamProvider.SIMULATOR,
        )
        self.assertTrue(
            reading.is_simulated
        )
        self.assertTrue(
            reading.used_historical_calibration
        )
        self.assertIsNone(
            reading.water_level_m
        )
        self.assertIsNone(
            reading.retrieved_at
        )
        self.assertIn(
            "2018-10-12",
            reading.external_reference,
        )

    def test_repeated_storage_is_idempotent(self):
        first = store_simulated_iot_point(
            self.county,
            self.point,
        )
        second = store_simulated_iot_point(
            self.county,
            self.point,
        )

        self.assertTrue(
            first.reading_created
        )
        self.assertFalse(
            second.device_created
        )
        self.assertFalse(
            second.reading_created
        )
        self.assertFalse(
            second.reading_updated
        )
        self.assertEqual(
            SensorDevice.objects.count(),
            1,
        )
        self.assertEqual(
            SensorReading.objects.count(),
            1,
        )

    def test_dry_run_rolls_back_device_and_reading(self):
        summary = store_simulated_iot_point(
            self.county,
            self.point,
            dry_run=True,
        )

        self.assertTrue(
            summary.dry_run
        )
        self.assertEqual(
            SensorDevice.objects.count(),
            0,
        )
        self.assertEqual(
            SensorReading.objects.count(),
            0,
        )

    def test_conflicting_device_origin_is_rejected(self):
        SensorDevice.objects.create(
            device_id="SIMULATED-030-001",
            name="Conflicting device",
            county=self.county,
            latitude=self.county.latitude,
            longitude=self.county.longitude,
            data_origin=(
                SensorDevice.DataOrigin.PHYSICAL
            ),
        )

        with self.assertRaisesRegex(
            SimulatedIoTStorageError,
            "is not a simulated device",
        ):
            store_simulated_iot_point(
                self.county,
                self.point,
            )