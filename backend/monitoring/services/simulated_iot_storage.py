from dataclasses import dataclass
from datetime import timezone as datetime_timezone

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from monitoring.models import (
    SensorDevice,
    SensorReading,
)


class SimulatedIoTStorageError(RuntimeError):
    """Raised when simulated telemetry cannot be stored safely."""


@dataclass(frozen=True)
class SimulatedIoTStorageSummary:
    device_id: str
    message_id: str
    device_created: bool
    reading_created: bool
    reading_updated: bool
    dry_run: bool


def _message_id(
    county,
    recorded_at,
):
    utc_time = recorded_at.astimezone(
        datetime_timezone.utc
    )

    return (
        f"SIMULATED-{county.code}-"
        f"{utc_time.strftime('%Y%m%dT%H%M%SZ')}"
    )


@transaction.atomic
def store_simulated_iot_point(
    county,
    point,
    *,
    dry_run=False,
):
    if county.pk is None:
        raise SimulatedIoTStorageError(
            "The county must be saved before storing telemetry."
        )

    if county.latitude is None or county.longitude is None:
        raise SimulatedIoTStorageError(
            f"{county.name} does not have coordinates."
        )

    if timezone.is_naive(point.recorded_at):
        raise SimulatedIoTStorageError(
            "The simulated reading time must be timezone-aware."
        )

    device_id = f"SIMULATED-{county.code}-001"

    device, device_created = (
        SensorDevice.objects.get_or_create(
            device_id=device_id,
            defaults={
                "name": (
                    f"{county.name} Historical "
                    "Simulation Sensor"
                ),
                "county": county,
                "latitude": county.latitude,
                "longitude": county.longitude,
                "data_origin": (
                    SensorDevice.DataOrigin.SIMULATED
                ),
                "is_active": True,
            },
        )
    )

    if not device_created:
        if device.county_id != county.pk:
            raise SimulatedIoTStorageError(
                f"Device {device_id} belongs to another county."
            )

        if (
            device.data_origin
            != SensorDevice.DataOrigin.SIMULATED
        ):
            raise SimulatedIoTStorageError(
                f"Device {device_id} is not a simulated device."
            )

    device.name = (
        f"{county.name} Historical Simulation Sensor"
    )
    device.latitude = county.latitude
    device.longitude = county.longitude
    device.is_active = True

    try:
        device.full_clean()
    except ValidationError as exc:
        raise SimulatedIoTStorageError(
            f"Invalid simulated device: {exc.messages}"
        ) from exc

    device.save()

    message_id = _message_id(
        county,
        point.recorded_at,
    )

    reading_values = {
        "device": device,
        "recorded_at": point.recorded_at,
        "precipitation_mm": point.precipitation_mm,
        "temperature_c": point.temperature_c,
        "relative_humidity_pct": (
            point.relative_humidity_pct
        ),
        "soil_wetness_fraction": (
            point.soil_wetness_fraction
        ),
        "water_level_m": point.water_level_m,
        "battery_pct": point.battery_pct,
        "upstream_provider": (
            SensorReading.UpstreamProvider.SIMULATOR
        ),
        "retrieved_at": None,
        "external_reference": (
            "NASA POWER historical calibration "
            f"{point.calibration_reference_date}"
        ),
        "used_historical_calibration": True,
        "is_simulated": True,
    }

    reading = SensorReading.objects.filter(
        message_id=message_id
    ).first()

    reading_created = reading is None
    reading_updated = False

    if reading is None:
        reading = SensorReading(
            message_id=message_id,
            **reading_values,
        )
    else:
        if reading.device_id != device.pk:
            raise SimulatedIoTStorageError(
                f"Message {message_id} belongs to another device."
            )

        if reading.recorded_at != point.recorded_at:
            raise SimulatedIoTStorageError(
                f"Message {message_id} has a different timestamp."
            )

        comparable_fields = (
            "precipitation_mm",
            "temperature_c",
            "relative_humidity_pct",
            "soil_wetness_fraction",
            "water_level_m",
            "battery_pct",
            "upstream_provider",
            "retrieved_at",
            "external_reference",
            "used_historical_calibration",
            "is_simulated",
        )

        reading_updated = any(
            getattr(reading, field_name)
            != reading_values[field_name]
            for field_name in comparable_fields
        )

        for field_name, value in reading_values.items():
            setattr(
                reading,
                field_name,
                value,
            )

    try:
        reading.full_clean()
    except ValidationError as exc:
        raise SimulatedIoTStorageError(
            f"Invalid simulated reading: {exc.messages}"
        ) from exc

    reading.save()

    device.last_seen_at = point.recorded_at
    device.save(
        update_fields=[
            "last_seen_at",
            "updated_at",
        ]
    )

    summary = SimulatedIoTStorageSummary(
        device_id=device_id,
        message_id=message_id,
        device_created=device_created,
        reading_created=reading_created,
        reading_updated=reading_updated,
        dry_run=dry_run,
    )

    if dry_run:
        transaction.set_rollback(True)

    return summary