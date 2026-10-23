from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from monitoring.models import (
    County,
    EnvironmentalObservation,
    SensorDevice,
    SensorReading,
)


class IoTTelemetryModelTests(TestCase):
    def setUp(self):
        self.county = County.objects.create(
            code="047",
            name="Nairobi",
            slug="nairobi",
            latitude=Decimal("-1.286389"),
            longitude=Decimal("36.817223"),
        )
        self.device = SensorDevice.objects.create(
            device_id="SIM-NAIROBI-001",
            name="Nairobi River Simulator",
            county=self.county,
            latitude=Decimal("-1.292100"),
            longitude=Decimal("36.821900"),
            data_origin=SensorDevice.DataOrigin.SIMULATED,
        )
        self.recorded_at = timezone.now()

    def build_reading(self, **overrides):
        values = {
            "device": self.device,
            "message_id": "SIM-NAIROBI-001-000001",
            "recorded_at": self.recorded_at,
            "precipitation_mm": Decimal("12.500"),
            "temperature_c": Decimal("23.40"),
            "relative_humidity_pct": Decimal("78.500"),
            "soil_wetness_fraction": Decimal("0.640000"),
            "water_level_m": Decimal("2.350"),
            "battery_pct": Decimal("91.500"),
            "upstream_provider": (
                SensorReading.UpstreamProvider.SIMULATOR
            ),
            "retrieved_at": None,
            "external_reference": "",
            "used_historical_calibration": True,
            "is_simulated": True,
        }
        values.update(overrides)
        return SensorReading(**values)

    def test_simulated_device_is_identified_explicitly(self):
        self.assertTrue(self.device.is_simulated)
        self.assertEqual(
            self.device.data_origin,
            SensorDevice.DataOrigin.SIMULATED,
        )

    def test_valid_simulated_reading_can_be_saved(self):
        reading = self.build_reading()

        reading.full_clean()
        reading.save()

        self.assertEqual(SensorReading.objects.count(), 1)
        self.assertTrue(reading.is_simulated)
        self.assertEqual(reading.device, self.device)
        self.assertIsNotNone(reading.received_at)

    def test_reading_provenance_must_match_device(self):
        reading = self.build_reading(
            is_simulated=False,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Reading provenance must match the sensor device",
        ):
            reading.full_clean()

    def test_duplicate_message_id_is_rejected(self):
        first = self.build_reading()
        first.full_clean()
        first.save()

        duplicate = self.build_reading(
            recorded_at=(
                self.recorded_at + timedelta(minutes=5)
            ),
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_duplicate_device_timestamp_is_rejected(self):
        first = self.build_reading()
        first.full_clean()
        first.save()

        duplicate = self.build_reading(
            message_id="SIM-NAIROBI-001-000002",
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_invalid_measurement_ranges_are_rejected(self):
        invalid_values = {
            "precipitation_mm": Decimal("-0.001"),
            "temperature_c": Decimal("101.00"),
            "relative_humidity_pct": Decimal("100.001"),
            "soil_wetness_fraction": Decimal("1.000001"),
            "water_level_m": Decimal("-0.001"),
            "battery_pct": Decimal("100.001"),
        }

        for field_name, invalid_value in invalid_values.items():
            with self.subTest(field=field_name):
                reading = self.build_reading(
                    **{field_name: invalid_value}
                )

                with self.assertRaises(ValidationError):
                    reading.full_clean()

    def test_invalid_device_coordinates_are_rejected(self):
        invalid_coordinates = (
            {
                "device_id": "INVALID-LATITUDE",
                "latitude": Decimal("-90.000001"),
                "longitude": Decimal("36.800000"),
            },
            {
                "device_id": "INVALID-LONGITUDE",
                "latitude": Decimal("-1.280000"),
                "longitude": Decimal("180.000001"),
            },
        )

        for values in invalid_coordinates:
            with self.subTest(device_id=values["device_id"]):
                device = SensorDevice(
                    name="Invalid test sensor",
                    county=self.county,
                    data_origin=(
                        SensorDevice.DataOrigin.SIMULATED
                    ),
                    **values,
                )

                with self.assertRaises(ValidationError):
                    device.full_clean()

    def test_physical_device_rejects_simulated_reading(self):
        physical_device = SensorDevice.objects.create(
            device_id="PHYSICAL-NAIROBI-001",
            name="Physical Nairobi Sensor",
            county=self.county,
            latitude=Decimal("-1.300000"),
            longitude=Decimal("36.830000"),
            data_origin=SensorDevice.DataOrigin.PHYSICAL,
        )
        reading = self.build_reading(
            device=physical_device,
            message_id="PHYSICAL-NAIROBI-001-000001",
            is_simulated=True,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Reading provenance must match the sensor device",
        ):
            reading.full_clean()

    def test_iot_observation_sources_are_available(self):
        self.assertEqual(
            EnvironmentalObservation.Source.SIMULATED_IOT,
            "SIMULATED_IOT",
        )
        self.assertEqual(
            EnvironmentalObservation.Source.LIVE_API_IOT,
            "LIVE_API_IOT",
        )

    def test_live_api_assisted_device_is_not_simulated(self):
        device = SensorDevice.objects.create(
            device_id="LIVE-NAIROBI-001",
            name="Nairobi Live Weather Virtual Sensor",
            county=self.county,
            latitude=Decimal("-1.292100"),
            longitude=Decimal("36.821900"),
            data_origin=(
                SensorDevice.DataOrigin.LIVE_API_ASSISTED
            ),
        )

        self.assertFalse(device.is_simulated)

    def test_open_meteo_assisted_reading_is_valid(self):
        device = SensorDevice.objects.create(
            device_id="LIVE-NAIROBI-002",
            name="Nairobi Open-Meteo Virtual Sensor",
            county=self.county,
            latitude=Decimal("-1.292100"),
            longitude=Decimal("36.821900"),
            data_origin=(
                SensorDevice.DataOrigin.LIVE_API_ASSISTED
            ),
        )
        reading = self.build_reading(
            device=device,
            message_id="OPEN-METEO-NAIROBI-000001",
            water_level_m=None,
            upstream_provider=(
                SensorReading.UpstreamProvider.OPEN_METEO
            ),
            retrieved_at=timezone.now(),
            external_reference=(
                "https://api.open-meteo.com/v1/forecast"
            ),
            used_historical_calibration=False,
            is_simulated=False,
        )

        reading.full_clean()
        reading.save()

        self.assertIsNone(
            reading.water_level_m
        )
        self.assertEqual(
            reading.upstream_provider,
            SensorReading.UpstreamProvider.OPEN_METEO,
        )
        self.assertFalse(reading.is_simulated)
        self.assertFalse(
            reading.used_historical_calibration
        )

    def test_nasa_power_assisted_reading_is_valid(self):
        device = SensorDevice.objects.create(
            device_id="LIVE-NAIROBI-003",
            name="Nairobi NASA POWER Virtual Sensor",
            county=self.county,
            latitude=Decimal("-1.292100"),
            longitude=Decimal("36.821900"),
            data_origin=(
                SensorDevice.DataOrigin.LIVE_API_ASSISTED
            ),
        )
        reading = self.build_reading(
            device=device,
            message_id="NASA-POWER-NAIROBI-000001",
            upstream_provider=(
                SensorReading.UpstreamProvider.NASA_POWER
            ),
            retrieved_at=timezone.now(),
            external_reference=(
                "https://power.larc.nasa.gov/api/temporal/daily/point"
            ),
            used_historical_calibration=True,
            is_simulated=False,
        )

        reading.full_clean()

    def test_live_api_reading_requires_retrieval_time(self):
        device = SensorDevice.objects.create(
            device_id="LIVE-NAIROBI-004",
            name="Missing Retrieval Time Sensor",
            county=self.county,
            latitude=Decimal("-1.292100"),
            longitude=Decimal("36.821900"),
            data_origin=(
                SensorDevice.DataOrigin.LIVE_API_ASSISTED
            ),
        )
        reading = self.build_reading(
            device=device,
            message_id="OPEN-METEO-NAIROBI-000002",
            upstream_provider=(
                SensorReading.UpstreamProvider.OPEN_METEO
            ),
            external_reference=(
                "https://api.open-meteo.com/v1/forecast"
            ),
            is_simulated=False,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "External API readings require a retrieval time",
        ):
            reading.full_clean()

    def test_live_api_reading_requires_source_reference(self):
        device = SensorDevice.objects.create(
            device_id="LIVE-NAIROBI-005",
            name="Missing Source Reference Sensor",
            county=self.county,
            latitude=Decimal("-1.292100"),
            longitude=Decimal("36.821900"),
            data_origin=(
                SensorDevice.DataOrigin.LIVE_API_ASSISTED
            ),
        )
        reading = self.build_reading(
            device=device,
            message_id="OPEN-METEO-NAIROBI-000003",
            upstream_provider=(
                SensorReading.UpstreamProvider.OPEN_METEO
            ),
            retrieved_at=timezone.now(),
            external_reference="",
            is_simulated=False,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "External API readings require a source reference",
        ):
            reading.full_clean()

    def test_live_api_device_rejects_plain_simulator_provider(self):
        device = SensorDevice.objects.create(
            device_id="LIVE-NAIROBI-006",
            name="Invalid Provider Sensor",
            county=self.county,
            latitude=Decimal("-1.292100"),
            longitude=Decimal("36.821900"),
            data_origin=(
                SensorDevice.DataOrigin.LIVE_API_ASSISTED
            ),
        )
        reading = self.build_reading(
            device=device,
            message_id="INVALID-PROVIDER-000001",
            is_simulated=False,
        )

        with self.assertRaisesRegex(
            ValidationError,
            "must use Open-Meteo or NASA POWER",
        ):
            reading.full_clean()