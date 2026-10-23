import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


NASA_POWER_DAILY_URL = (
    "https://power.larc.nasa.gov"
    "/api/temporal/daily/point"
)
NASA_POWER_PARAMETERS = (
    "PRECTOTCORR",
    "T2M",
    "RH2M",
    "GWETROOT",
)
NASA_POWER_MISSING_VALUE = Decimal("-999")


class NasaPowerError(RuntimeError):
    """Raised when NASA POWER data cannot be safely retrieved."""
class NasaPowerNoDataError(NasaPowerError):
    """Raised when requested NASA POWER dates are not published yet."""


@dataclass(frozen=True)
class NasaPowerDailyPoint:
    observation_date: date
    precipitation_mm: Decimal
    temperature_c: Decimal
    relative_humidity_pct: Decimal
    soil_wetness_fraction: Decimal


def build_nasa_power_url(
    *,
    latitude,
    longitude,
    start_date,
    end_date,
):
    query = urlencode(
        {
            "parameters": ",".join(
                NASA_POWER_PARAMETERS
            ),
            "community": "AG",
            "longitude": str(longitude),
            "latitude": str(latitude),
            "start": start_date.strftime("%Y%m%d"),
            "end": end_date.strftime("%Y%m%d"),
            "format": "JSON",
        }
    )

    return f"{NASA_POWER_DAILY_URL}?{query}"


def _request_json(url, *, timeout):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Kenya-Flood-Risk-Platform/1.0"
            ),
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(
            request,
            timeout=timeout,
        ) as response:
            content = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise NasaPowerError(
            f"NASA POWER request failed: {exc}"
        ) from exc

    try:
        return json.loads(
            content.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise NasaPowerError(
            "NASA POWER returned an invalid JSON response."
        ) from exc


def _decimal_value(parameter, value, date_key):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise NasaPowerError(
            f"NASA POWER returned a non-numeric "
            f"{parameter} value for {date_key}."
        ) from exc

    if not parsed.is_finite():
        raise NasaPowerError(
            f"NASA POWER returned a non-finite "
            f"{parameter} value for {date_key}."
        )

    return parsed


def _validate_ranges(record):
    if record.precipitation_mm < 0:
        raise NasaPowerError(
            "NASA POWER precipitation cannot be negative."
        )

    if not Decimal("-100") <= record.temperature_c <= Decimal("100"):
        raise NasaPowerError(
            "NASA POWER temperature is outside the valid range."
        )

    if not (
        Decimal("0")
        <= record.relative_humidity_pct
        <= Decimal("100")
    ):
        raise NasaPowerError(
            "NASA POWER humidity is outside the valid range."
        )

    if not (
        Decimal("0")
        <= record.soil_wetness_fraction
        <= Decimal("1")
    ):
        raise NasaPowerError(
            "NASA POWER soil wetness is outside the valid range."
        )


def parse_nasa_power_response(payload):
    try:
        parameters = payload["properties"]["parameter"]
        parameter_values = {
            parameter: parameters[parameter]
            for parameter in NASA_POWER_PARAMETERS
        }
    except (KeyError, TypeError) as exc:
        raise NasaPowerError(
            "NASA POWER response is missing required parameters."
        ) from exc

    date_keys = sorted(
        set.intersection(
            *[
                set(values)
                for values in parameter_values.values()
            ]
        )
    )
    records = []

    for date_key in date_keys:
        values = {
            parameter: _decimal_value(
                parameter,
                parameter_values[parameter][date_key],
                date_key,
            )
            for parameter in NASA_POWER_PARAMETERS
        }

        if any(
            value == NASA_POWER_MISSING_VALUE
            for value in values.values()
        ):
            continue

        try:
            observation_date = datetime.strptime(
                date_key,
                "%Y%m%d",
            ).date()
        except ValueError as exc:
            raise NasaPowerError(
                f"NASA POWER returned an invalid date: {date_key}"
            ) from exc

        record = NasaPowerDailyPoint(
            observation_date=observation_date,
            precipitation_mm=values["PRECTOTCORR"],
            temperature_c=values["T2M"],
            relative_humidity_pct=values["RH2M"],
            soil_wetness_fraction=values["GWETROOT"],
        )
        _validate_ranges(record)
        records.append(record)

    if not records:
        raise NasaPowerNoDataError(
            "NASA POWER returned no complete daily records."
        )

    return tuple(records)


def fetch_nasa_power_daily_point(
    *,
    latitude,
    longitude,
    start_date,
    end_date,
    timeout=30,
):
    if start_date > end_date:
        raise NasaPowerError(
            "NASA POWER start date must be on or before end date."
        )

    latitude = Decimal(str(latitude))
    longitude = Decimal(str(longitude))

    if not Decimal("-90") <= latitude <= Decimal("90"):
        raise NasaPowerError(
            "NASA POWER latitude is outside the valid range."
        )

    if not Decimal("-180") <= longitude <= Decimal("180"):
        raise NasaPowerError(
            "NASA POWER longitude is outside the valid range."
        )

    url = build_nasa_power_url(
        latitude=latitude,
        longitude=longitude,
        start_date=start_date,
        end_date=end_date,
    )
    payload = _request_json(
        url,
        timeout=timeout,
    )

    return parse_nasa_power_response(payload)