import json
import ssl
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.test import SimpleTestCase

from monitoring.services.open_meteo import (
    OpenMeteoError,
    OpenMeteoNoDataError,
    build_open_meteo_url,
    fetch_open_meteo_daily_point,
    parse_open_meteo_daily,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return BytesIO(
            json.dumps(self.payload).encode("utf-8")
        )

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class OpenMeteoServiceTests(SimpleTestCase):
    def setUp(self):
        self.observation_date = date(2026, 10, 23)
        self.payload = {
            "hourly": {
                "time": [
                    "2026-10-23T00:00",
                    "2026-10-23T01:00",
                    "2026-10-23T02:00",
                ],
                "precipitation": [1.0, 2.5, 0.5],
                "temperature_2m": [20.0, 22.0, 24.0],
                "relative_humidity_2m": [70, 80, 75],
                "soil_moisture_0_to_1cm": [
                    0.4,
                    0.6,
                    0.5,
                ],
            }
        }

    def test_build_url_uses_expected_parameters(self):
        url = build_open_meteo_url(
            latitude=Decimal("0.676445"),
            longitude=Decimal("35.940327"),
            observation_date=self.observation_date,
        )
        query = parse_qs(urlparse(url).query)

        self.assertEqual(
            query["start_date"],
            ["2026-10-23"],
        )
        self.assertEqual(
            query["end_date"],
            ["2026-10-23"],
        )
        self.assertEqual(
            query["timezone"],
            ["Africa/Nairobi"],
        )
        self.assertIn(
            "soil_moisture_0_to_1cm",
            query["hourly"][0],
        )

    def test_response_is_aggregated_into_daily_point(self):
        result = parse_open_meteo_daily(
            self.payload,
            observation_date=self.observation_date,
        )

        self.assertEqual(
            result.precipitation_mm,
            Decimal("4.000"),
        )
        self.assertEqual(
            result.temperature_c,
            Decimal("22.00"),
        )
        self.assertEqual(
            result.relative_humidity_pct,
            Decimal("75.000"),
        )
        self.assertEqual(
            result.soil_wetness_mean_fraction,
            Decimal("0.500000"),
        )
        self.assertEqual(
            result.soil_wetness_max_fraction,
            Decimal("0.600000"),
        )

    def test_incomplete_hours_are_skipped(self):
        self.payload["hourly"]["temperature_2m"][1] = None

        result = parse_open_meteo_daily(
            self.payload,
            observation_date=self.observation_date,
        )

        self.assertEqual(
            result.precipitation_mm,
            Decimal("1.500"),
        )
        self.assertEqual(
            result.temperature_c,
            Decimal("22.00"),
        )

    def test_no_complete_records_is_rejected(self):
        self.payload["hourly"]["temperature_2m"] = [
            None,
            None,
            None,
        ]

        with self.assertRaises(OpenMeteoNoDataError):
            parse_open_meteo_daily(
                self.payload,
                observation_date=self.observation_date,
            )

    def test_mismatched_hourly_arrays_are_rejected(self):
        self.payload["hourly"]["precipitation"] = [1.0]

        with self.assertRaisesRegex(
            OpenMeteoError,
            "different lengths",
        ):
            parse_open_meteo_daily(
                self.payload,
                observation_date=self.observation_date,
            )

    def test_invalid_measurement_range_is_rejected(self):
        self.payload[
            "hourly"
        ]["relative_humidity_2m"][0] = 120

        with self.assertRaisesRegex(
            OpenMeteoError,
            "humidity",
        ):
            parse_open_meteo_daily(
                self.payload,
                observation_date=self.observation_date,
            )

    @patch(
        "monitoring.services.open_meteo.urlopen"
    )
    def test_fetch_uses_open_meteo_api(
        self,
        urlopen_mock,
    ):
        urlopen_mock.return_value = Response(
            self.payload
        )

        result = fetch_open_meteo_daily_point(
            latitude=Decimal("0.676445"),
            longitude=Decimal("35.940327"),
            observation_date=self.observation_date,
            timeout=15,
        )

        self.assertEqual(
            result.observation_date,
            self.observation_date,
        )
        urlopen_mock.assert_called_once()
        self.assertEqual(
            urlopen_mock.call_args.kwargs["timeout"],
            15,
        )
        ssl_context = (
            urlopen_mock.call_args.kwargs["context"]
        )

        self.assertEqual(
            ssl_context.verify_mode,
            ssl.CERT_REQUIRED,
        )
        self.assertTrue(
            ssl_context.check_hostname
        )

    def test_invalid_timeout_is_rejected(self):
        with self.assertRaisesRegex(
            OpenMeteoError,
            "timeout",
        ):
            fetch_open_meteo_daily_point(
                latitude=Decimal("0.676445"),
                longitude=Decimal("35.940327"),
                observation_date=self.observation_date,
                timeout=0,
            )