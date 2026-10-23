import json
import ssl
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi


OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
)

HOURLY_PARAMETERS = (
    "precipitation",
    "temperature_2m",
    "relative_humidity_2m",
    "soil_moisture_0_to_1cm",
)


class OpenMeteoError(RuntimeError):
    """Raised when Open-Meteo data cannot be used safely."""


class OpenMeteoNoDataError(OpenMeteoError):
    """Raised when no complete hourly records are available."""


@dataclass(frozen=True)
class OpenMeteoDailyPoint:
    observation_date: date
    precipitation_mm: Decimal
    temperature_c: Decimal
    relative_humidity_pct: Decimal
    soil_wetness_mean_fraction: Decimal
    soil_wetness_max_fraction: Decimal


def build_open_meteo_url(
    *,
    latitude,
    longitude,
    observation_date,
):
    query = urlencode(
        {
            "latitude": str(latitude),
            "longitude": str(longitude),
            "hourly": ",".join(HOURLY_PARAMETERS),
            "start_date": observation_date.isoformat(),
            "end_date": observation_date.isoformat(),
            "timezone": "Africa/Nairobi",
            "temperature_unit": "celsius",
            "precipitation_unit": "mm",
            "cell_selection": "land",
        }
    )

    return f"{OPEN_METEO_URL}?{query}"


def _decimal_value(value, field_name):
    if value is None or isinstance(value, bool):
        raise OpenMeteoError(
            f"Invalid {field_name} value returned by Open-Meteo."
        )

    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OpenMeteoError(
            f"Invalid {field_name} value returned by Open-Meteo."
        ) from exc

    if not decimal_value.is_finite():
        raise OpenMeteoError(
            f"Non-finite {field_name} value returned by Open-Meteo."
        )

    return decimal_value


def _validate_measurements(
    *,
    precipitation,
    temperature,
    humidity,
    soil_wetness,
):
    if precipitation < 0:
        raise OpenMeteoError(
            "Open-Meteo precipitation cannot be negative."
        )

    if not Decimal("-100") <= temperature <= Decimal("100"):
        raise OpenMeteoError(
            "Open-Meteo temperature is outside the valid range."
        )

    if not Decimal("0") <= humidity <= Decimal("100"):
        raise OpenMeteoError(
            "Open-Meteo humidity is outside the valid range."
        )

    if not Decimal("0") <= soil_wetness <= Decimal("1"):
        raise OpenMeteoError(
            "Open-Meteo soil moisture is outside the valid range."
        )


def parse_open_meteo_daily(
    payload,
    *,
    observation_date,
):
    hourly = payload.get("hourly")

    if not isinstance(hourly, dict):
        raise OpenMeteoError(
            "Open-Meteo response is missing hourly data."
        )

    times = hourly.get("time")

    if not isinstance(times, list):
        raise OpenMeteoError(
            "Open-Meteo response is missing hourly timestamps."
        )

    parameter_values = {}

    for parameter in HOURLY_PARAMETERS:
        values = hourly.get(parameter)

        if not isinstance(values, list):
            raise OpenMeteoError(
                "Open-Meteo response is missing "
                f"{parameter}."
            )

        if len(values) != len(times):
            raise OpenMeteoError(
                "Open-Meteo hourly arrays have different lengths."
            )

        parameter_values[parameter] = values

    precipitation_values = []
    temperature_values = []
    humidity_values = []
    soil_values = []

    for index, timestamp in enumerate(times):
        if (
            not isinstance(timestamp, str)
            or not timestamp.startswith(
                observation_date.isoformat()
            )
        ):
            continue

        raw_values = {
            parameter: parameter_values[parameter][index]
            for parameter in HOURLY_PARAMETERS
        }

        if any(
            value is None
            for value in raw_values.values()
        ):
            continue

        precipitation = _decimal_value(
            raw_values["precipitation"],
            "precipitation",
        )
        temperature = _decimal_value(
            raw_values["temperature_2m"],
            "temperature",
        )
        humidity = _decimal_value(
            raw_values["relative_humidity_2m"],
            "humidity",
        )
        soil_wetness = _decimal_value(
            raw_values["soil_moisture_0_to_1cm"],
            "soil moisture",
        )

        _validate_measurements(
            precipitation=precipitation,
            temperature=temperature,
            humidity=humidity,
            soil_wetness=soil_wetness,
        )

        precipitation_values.append(precipitation)
        temperature_values.append(temperature)
        humidity_values.append(humidity)
        soil_values.append(soil_wetness)

    if not precipitation_values:
        raise OpenMeteoNoDataError(
            "Open-Meteo returned no complete hourly records."
        )

    record_count = Decimal(
        len(precipitation_values)
    )

    return OpenMeteoDailyPoint(
        observation_date=observation_date,
        precipitation_mm=sum(
            precipitation_values,
            Decimal("0"),
        ).quantize(Decimal("0.001")),
        temperature_c=(
            sum(temperature_values, Decimal("0"))
            / record_count
        ).quantize(Decimal("0.01")),
        relative_humidity_pct=(
            sum(humidity_values, Decimal("0"))
            / record_count
        ).quantize(Decimal("0.001")),
        soil_wetness_mean_fraction=(
            sum(soil_values, Decimal("0"))
            / record_count
        ).quantize(Decimal("0.000001")),
        soil_wetness_max_fraction=max(
            soil_values
        ).quantize(Decimal("0.000001")),
    )


def fetch_open_meteo_daily_point(
    *,
    latitude,
    longitude,
    observation_date,
    timeout=30,
):
    if timeout <= 0:
        raise OpenMeteoError(
            "Open-Meteo timeout must be greater than zero."
        )

    url = build_open_meteo_url(
        latitude=latitude,
        longitude=longitude,
        observation_date=observation_date,
    )
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Kenya-Flood-Risk-Platform/1.0"
            ),
        },
    )
    ssl_context = ssl.create_default_context(
        cafile=certifi.where()
    )

    try:
        with urlopen(
            request,
            timeout=timeout,
            context=ssl_context,
        ) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise OpenMeteoError(
            f"Open-Meteo returned HTTP {exc.code}."
        ) from exc
    except URLError as exc:
        raise OpenMeteoError(
            f"Open-Meteo request failed: {exc.reason}"
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OpenMeteoError(
            "Open-Meteo returned invalid JSON."
        ) from exc

    if payload.get("error"):
        raise OpenMeteoError(
            "Open-Meteo rejected the request: "
            f"{payload.get('reason', 'unknown error')}."
        )

    return parse_open_meteo_daily(
        payload,
        observation_date=observation_date,
    )