import hashlib
import random
from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from monitoring.models import EnvironmentalObservation


class SimulatedIoTError(RuntimeError):
    """Raised when simulated telemetry cannot be generated safely."""


@dataclass(frozen=True)
class SimulatedIoTPoint:
    recorded_at: object
    precipitation_mm: Decimal
    temperature_c: Decimal
    relative_humidity_pct: Decimal
    soil_wetness_fraction: Decimal
    water_level_m: object
    battery_pct: Decimal
    calibration_observation_count: int
    calibration_reference_date: object


def _quantize(value, decimal_places):
    quantum = Decimal(1).scaleb(-decimal_places)

    return Decimal(str(value)).quantize(quantum)


def _clamp(value, minimum, maximum):
    return max(
        minimum,
        min(maximum, value),
    )


def _stable_random(
    county,
    recorded_at,
    seed,
):
    seed_text = (
        f"{county.code}|"
        f"{recorded_at.isoformat()}|"
        f"{seed if seed is not None else ''}"
    )
    digest = hashlib.sha256(
        seed_text.encode("utf-8")
    ).hexdigest()
    integer_seed = int(
        digest[:16],
        16,
    )

    return random.Random(integer_seed)


def generate_simulated_iot_point(
    county,
    *,
    recorded_at,
    seed=None,
):
    if county.pk is None:
        raise SimulatedIoTError(
            "The county must be saved before simulation."
        )

    if timezone.is_naive(recorded_at):
        raise SimulatedIoTError(
            "The simulated reading time must be timezone-aware."
        )

    historical_rows = list(
        EnvironmentalObservation.objects.filter(
            county=county,
            source=(
                EnvironmentalObservation.Source.NASA_POWER
            ),
            observation_date__year__lte=2025,
            observation_date__month=recorded_at.month,
            is_synthetic=False,
        )
        .order_by("observation_date")
        .values(
            "observation_date",
            "precipitation_max_mm",
            "temperature_mean_c",
            "relative_humidity_mean_pct",
            "soil_wetness_mean_fraction",
        )
    )

    if not historical_rows:
        raise SimulatedIoTError(
            "No real historical NASA POWER observations "
            f"are available for {county.name} in month "
            f"{recorded_at.month}."
        )

    generator = _stable_random(
        county,
        recorded_at,
        seed,
    )
    reference = generator.choice(
        historical_rows
    )

    precipitation = float(
        reference["precipitation_max_mm"]
    )
    temperature = float(
        reference["temperature_mean_c"]
    )
    humidity = float(
        reference["relative_humidity_mean_pct"]
    )
    soil_wetness = float(
        reference["soil_wetness_mean_fraction"]
    )

    precipitation *= generator.uniform(
        0.95,
        1.05,
    )
    temperature += generator.uniform(
        -0.50,
        0.50,
    )
    humidity += generator.uniform(
        -2.00,
        2.00,
    )
    soil_wetness += generator.uniform(
        -0.02,
        0.02,
    )
    battery = generator.uniform(
        70.0,
        100.0,
    )

    precipitation = max(
        0.0,
        precipitation,
    )
    temperature = _clamp(
        temperature,
        -100.0,
        100.0,
    )
    humidity = _clamp(
        humidity,
        0.0,
        100.0,
    )
    soil_wetness = _clamp(
        soil_wetness,
        0.0,
        1.0,
    )

    return SimulatedIoTPoint(
        recorded_at=recorded_at,
        precipitation_mm=_quantize(
            precipitation,
            3,
        ),
        temperature_c=_quantize(
            temperature,
            2,
        ),
        relative_humidity_pct=_quantize(
            humidity,
            3,
        ),
        soil_wetness_fraction=_quantize(
            soil_wetness,
            6,
        ),
        water_level_m=None,
        battery_pct=_quantize(
            battery,
            3,
        ),
        calibration_observation_count=len(
            historical_rows
        ),
        calibration_reference_date=(
            reference["observation_date"]
        ),
    )