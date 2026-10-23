import math
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from monitoring.models import (
    EnvironmentalObservation,
    SensorDevice,
    SensorReading,
)
from monitoring.services.open_meteo import (
    OpenMeteoDailyPoint,
    build_open_meteo_url,
)


class OpenMeteoStorageError(RuntimeError):
    """Raised when Open-Meteo telemetry cannot be stored safely."""


@dataclass(frozen=True)
class OpenMeteoStorageSummary:
    device_created: bool
    reading_created: bool
    reading_updated: bool
    observation_created: bool
    observation_updated: bool
    observation_preserved: bool
    dry_run: bool


def _month_encoding(observation_date):
    angle = (
        2
        * math.pi
        * (observation_date.month - 1)
        / 12
    )

    return (
        Decimal(str(math.sin(angle))).quantize(
            Decimal("0.00000001")
        ),
        Decimal(str(math.cos(angle))).quantize(
            Decimal("0.00000001")
        ),
    )


def _recorded_at(observation_date):
    local_midnight = datetime.combine(
        observation_date,
        time.min,
    )

    return timezone.make_aware(
        local_midnight,
        ZoneInfo("Africa/Nairobi"),
    )


def _validate(instance, description):
    try:
        instance.full_clean()
    except ValidationError as exc:
        raise OpenMeteoStorageError(
            f"Invalid {description}: {exc.messages}"
        ) from exc


def _values_changed(instance, values):
    return any(
        getattr(instance, field_name) != value
        for field_name, value in values.items()
    )


@transaction.atomic
def store_open_meteo_daily_point(
    county,
    daily_point,
    *,
    retrieved_at=None,
    dry_run=False,
):
    if county.pk is None:
        raise OpenMeteoStorageError(
            "The county must be saved before storing telemetry."
        )

    if county.latitude is None or county.longitude is None:
        raise OpenMeteoStorageError(
            f"{county.name} does not have coordinates."
        )

    if not isinstance(
        daily_point,
        OpenMeteoDailyPoint,
    ):
        raise OpenMeteoStorageError(
            "A valid Open-Meteo daily point is required."
        )

    retrieved_at = retrieved_at or timezone.now()

    if timezone.is_naive(retrieved_at):
        raise OpenMeteoStorageError(
            "Open-Meteo retrieval time must be timezone-aware."
        )

    device_id = f"OPEN-METEO-{county.code}"
    device = SensorDevice.objects.filter(
        device_id=device_id
    ).first()
    device_created = device is None

    if device is None:
        device = SensorDevice(
            device_id=device_id,
            name=(
                f"{county.name} Open-Meteo "
                "Virtual Sensor"
            ),
            county=county,
            latitude=county.latitude,
            longitude=county.longitude,
            data_origin=(
                SensorDevice.DataOrigin.LIVE_API_ASSISTED
            ),
            is_active=True,
            last_seen_at=retrieved_at,
        )
    else:
        if device.county_id != county.pk:
            raise OpenMeteoStorageError(
                f"Device {device_id} belongs to another county."
            )

        if (
            device.data_origin
            != SensorDevice.DataOrigin.LIVE_API_ASSISTED
        ):
            raise OpenMeteoStorageError(
                f"Device {device_id} is not live API-assisted."
            )

        device.name = (
            f"{county.name} Open-Meteo Virtual Sensor"
        )
        device.latitude = county.latitude
        device.longitude = county.longitude
        device.is_active = True
        device.last_seen_at = retrieved_at

    _validate(device, "Open-Meteo sensor device")
    device.save()

    source_url = build_open_meteo_url(
        latitude=county.latitude,
        longitude=county.longitude,
        observation_date=(
            daily_point.observation_date
        ),
    )
    reading_values = {
        "device": device,
        "recorded_at": _recorded_at(
            daily_point.observation_date
        ),
        "precipitation_mm": (
            daily_point.precipitation_mm
        ),
        "temperature_c": daily_point.temperature_c,
        "relative_humidity_pct": (
            daily_point.relative_humidity_pct
        ),
        "soil_wetness_fraction": (
            daily_point.soil_wetness_mean_fraction
        ),
        "water_level_m": None,
        "battery_pct": None,
        "upstream_provider": (
            SensorReading.UpstreamProvider.OPEN_METEO
        ),
        "retrieved_at": retrieved_at,
        "external_reference": source_url,
        "used_historical_calibration": False,
        "is_simulated": False,
    }
    message_id = (
        f"OPEN_METEO_{county.code}_"
        f"{daily_point.observation_date:%Y%m%d}"
    )
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
        _validate(reading, "Open-Meteo sensor reading")
        reading.save()
    else:
        if reading.device_id != device.pk:
            raise OpenMeteoStorageError(
                f"Message {message_id} belongs to another device."
            )

        reading_updated = _values_changed(
            reading,
            reading_values,
        )

        if reading_updated:
            for field_name, value in reading_values.items():
                setattr(reading, field_name, value)

            _validate(
                reading,
                "Open-Meteo sensor reading update",
            )
            reading.save(
                update_fields=[
                    *reading_values.keys(),
                ]
            )

    month_sin, month_cos = _month_encoding(
        daily_point.observation_date
    )
    observation_values = {
        "precipitation_max_mm": (
            daily_point.precipitation_mm
        ),
        "temperature_mean_c": (
            daily_point.temperature_c
        ),
        "relative_humidity_mean_pct": (
            daily_point.relative_humidity_pct
        ),
        "soil_wetness_mean_fraction": (
            daily_point.soil_wetness_mean_fraction
        ),
        "soil_wetness_max_fraction": (
            daily_point.soil_wetness_max_fraction
        ),
        "month_sin": month_sin,
        "month_cos": month_cos,
        "source": (
            EnvironmentalObservation.Source.LIVE_API_IOT
        ),
        "source_record_id": message_id,
        "is_synthetic": False,
        "quality_review_required": True,
    }
    observation = (
        EnvironmentalObservation.objects.filter(
            county=county,
            observation_date=(
                daily_point.observation_date
            ),
        ).first()
    )
    observation_created = False
    observation_updated = False
    observation_preserved = False

    if observation is None:
        observation = EnvironmentalObservation(
            county=county,
            observation_date=(
                daily_point.observation_date
            ),
            **observation_values,
        )
        _validate(
            observation,
            "Open-Meteo environmental observation",
        )
        observation.save()
        observation_created = True
    elif (
        observation.source
        != EnvironmentalObservation.Source.LIVE_API_IOT
    ):
        observation_preserved = True
    elif _values_changed(
        observation,
        observation_values,
    ):
        if observation.predictions.exists():
            observation_preserved = True
        else:
            for field_name, value in observation_values.items():
                setattr(
                    observation,
                    field_name,
                    value,
                )

            _validate(
                observation,
                "Open-Meteo observation update",
            )
            observation.save(
                update_fields=[
                    *observation_values.keys(),
                    "updated_at",
                ]
            )
            observation_updated = True

    if dry_run:
        transaction.set_rollback(True)

    return OpenMeteoStorageSummary(
        device_created=device_created,
        reading_created=reading_created,
        reading_updated=reading_updated,
        observation_created=observation_created,
        observation_updated=observation_updated,
        observation_preserved=observation_preserved,
        dry_run=dry_run,
    )