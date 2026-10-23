from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.test import SimpleTestCase

from monitoring.services.nasa_power import (
    NasaPowerError,
    NasaPowerNoDataError,
    build_nasa_power_url,
    fetch_nasa_power_daily_point,
    parse_nasa_power_response,
)


class NasaPowerServiceTests(SimpleTestCase):
    def build_payload(self):
        return {
            "properties": {
                "parameter": {
                    "PRECTOTCORR": {
                        "20260101": 12.5,
                        "20260102": 4.25,
                    },
                    "T2M": {
                        "20260101": 23.4,
                        "20260102": 24.1,
                    },
                    "RH2M": {
                        "20260101": 78.5,
                        "20260102": 75.0,
                    },
                    "GWETROOT": {
                        "20260101": 0.64,
                        "20260102": 0.61,
                    },
                }
            }
        }

    def test_build_url_uses_expected_parameters(self):
        url = build_nasa_power_url(
            latitude=Decimal("-1.286389"),
            longitude=Decimal("36.817223"),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        query = parse_qs(urlparse(url).query)

        self.assertEqual(
            query["parameters"],
            ["PRECTOTCORR,T2M,RH2M,GWETROOT"],
        )
        self.assertEqual(query["community"], ["AG"])
        self.assertEqual(query["start"], ["20260101"])
        self.assertEqual(query["end"], ["20260131"])
        self.assertEqual(query["format"], ["JSON"])

    def test_response_is_parsed_into_daily_points(self):
        records = parse_nasa_power_response(
            self.build_payload()
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(
            records[0].observation_date,
            date(2026, 1, 1),
        )
        self.assertEqual(
            records[0].precipitation_mm,
            Decimal("12.5"),
        )
        self.assertEqual(
            records[0].soil_wetness_fraction,
            Decimal("0.64"),
        )

    def test_incomplete_days_are_skipped(self):
        payload = self.build_payload()
        payload["properties"]["parameter"][
            "GWETROOT"
        ]["20260102"] = -999

        records = parse_nasa_power_response(
            payload
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0].observation_date,
            date(2026, 1, 1),
        )

    def test_missing_required_parameter_is_rejected(self):
        payload = self.build_payload()
        del payload["properties"]["parameter"]["RH2M"]

        with self.assertRaisesRegex(
            NasaPowerError,
            "missing required parameters",
        ):
            parse_nasa_power_response(payload)

    def test_invalid_measurement_range_is_rejected(self):
        payload = self.build_payload()
        payload["properties"]["parameter"][
            "RH2M"
        ]["20260101"] = 101

        with self.assertRaisesRegex(
            NasaPowerError,
            "humidity is outside",
        ):
            parse_nasa_power_response(payload)

    def test_no_complete_records_is_rejected(self):
        payload = self.build_payload()

        for values in payload[
            "properties"
        ]["parameter"].values():
            values["20260101"] = -999
            values["20260102"] = -999

        with self.assertRaisesRegex(
            NasaPowerNoDataError,
            "no complete daily records",
        ):
            parse_nasa_power_response(payload)

    def test_invalid_date_range_is_rejected(self):
        with self.assertRaisesRegex(
            NasaPowerError,
            "start date must be on or before end date",
        ):
            fetch_nasa_power_daily_point(
                latitude=Decimal("-1.286389"),
                longitude=Decimal("36.817223"),
                start_date=date(2026, 2, 1),
                end_date=date(2026, 1, 1),
            )

    @patch(
        "monitoring.services.nasa_power._request_json"
    )
    def test_fetch_uses_api_and_returns_records(
        self,
        request_json,
    ):
        request_json.return_value = self.build_payload()

        records = fetch_nasa_power_daily_point(
            latitude=Decimal("-1.286389"),
            longitude=Decimal("36.817223"),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
        )

        self.assertEqual(len(records), 2)
        request_json.assert_called_once()
        requested_url = request_json.call_args.args[0]
        self.assertIn(
            "power.larc.nasa.gov",
            requested_url,
        )