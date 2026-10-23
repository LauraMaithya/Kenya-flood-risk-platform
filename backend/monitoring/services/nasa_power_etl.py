import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class NasaPowerETLError(RuntimeError):
    """Raised when NASA POWER point data cannot be aggregated."""


@dataclass(frozen=True)
class NasaPowerCountyDay:
    observation_date: date
    precipitation_max_mm: Decimal
    temperature_mean_c: Decimal
    relative_humidity_mean_pct: Decimal
    soil_wetness_mean_fraction: Decimal
    soil_wetness_max_fraction: Decimal
    month_sin: Decimal
    month_cos: Decimal
    contributing_points: int


def _quantize(value, precision):
    return value.quantize(Decimal(precision))


def _mean(values):
    return sum(values, Decimal("0")) / Decimal(
        len(values)
    )


def _seasonal_features(month):
    angle = (
        2.0
        * math.pi
        * (month - 1)
        / 12.0
    )
    month_sin = Decimal(str(math.sin(angle)))
    month_cos = Decimal(str(math.cos(angle)))
    zero_tolerance = Decimal("0.000000005")

    if abs(month_sin) < zero_tolerance:
        month_sin = Decimal("0")

    if abs(month_cos) < zero_tolerance:
        month_cos = Decimal("0")

    return (
        _quantize(month_sin, "0.00000001"),
        _quantize(month_cos, "0.00000001"),
    )


def _records_by_date(records, point_number):
    indexed = {}

    for record in records:
        if record.observation_date in indexed:
            raise NasaPowerETLError(
                "NASA POWER point "
                f"{point_number} contains duplicate date "
                f"{record.observation_date}."
            )

        indexed[record.observation_date] = record

    if not indexed:
        raise NasaPowerETLError(
            f"NASA POWER point {point_number} has no records."
        )

    return indexed


def aggregate_nasa_power_points(point_records):
    point_records = [
        tuple(records)
        for records in point_records
    ]

    if not point_records:
        raise NasaPowerETLError(
            "At least one NASA POWER point is required."
        )

    indexed_points = [
        _records_by_date(records, point_number)
        for point_number, records in enumerate(
            point_records,
            start=1,
        )
    ]
    common_dates = set.intersection(
        *[
            set(records)
            for records in indexed_points
        ]
    )

    if not common_dates:
        raise NasaPowerETLError(
            "NASA POWER points have no common complete dates."
        )

    county_days = []

    for observation_date in sorted(common_dates):
        records = [
            point[observation_date]
            for point in indexed_points
        ]
        precipitation_values = [
            record.precipitation_mm
            for record in records
        ]
        temperature_values = [
            record.temperature_c
            for record in records
        ]
        humidity_values = [
            record.relative_humidity_pct
            for record in records
        ]
        soil_values = [
            record.soil_wetness_fraction
            for record in records
        ]
        month_sin, month_cos = _seasonal_features(
            observation_date.month
        )

        county_days.append(
            NasaPowerCountyDay(
                observation_date=observation_date,
                precipitation_max_mm=_quantize(
                    max(precipitation_values),
                    "0.001",
                ),
                temperature_mean_c=_quantize(
                    _mean(temperature_values),
                    "0.01",
                ),
                relative_humidity_mean_pct=_quantize(
                    _mean(humidity_values),
                    "0.001",
                ),
                soil_wetness_mean_fraction=_quantize(
                    _mean(soil_values),
                    "0.000001",
                ),
                soil_wetness_max_fraction=_quantize(
                    max(soil_values),
                    "0.000001",
                ),
                month_sin=month_sin,
                month_cos=month_cos,
                contributing_points=len(records),
            )
        )

    return tuple(county_days)