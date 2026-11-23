from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
from django.test import SimpleTestCase
import xarray as xr

from monitoring.services.monthly_outlook_model import prepare_samples
from monitoring.services.seasonal_forecast import normalise_c3s_files


class SeasonalForecastNormalisationTests(SimpleTestCase):
    def test_converts_issue_time_grid_to_county_month_rows(self):
        values = np.full((2, 3, 2, 2), 0.000001)
        dataset = xr.Dataset(
            {
                "total_precipitation_anomaly": (
                    ("time", "forecastMonth", "latitude", "longitude"),
                    values,
                    {"units": "m s-1"},
                )
            },
            coords={
                "time": pd.to_datetime(["2025-11-01", "2026-11-01"]),
                "forecastMonth": [2, 3, 4],
                "latitude": [0.0, -1.0],
                "longitude": [36.0, 37.0],
            },
        )
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "forecast.nc"
            dataset.to_netcdf(path)
            result = normalise_c3s_files(
                [path],
                issue_month=11,
                county_locations={"Test County": (-0.8, 36.9)},
            )
        self.assertEqual(len(result), 6)
        self.assertEqual(set(result.issue_month), {"2025-11", "2026-11"})
        self.assertEqual(set(result.target_month), {
            "2025-12", "2026-01", "2026-02",
            "2026-12", "2027-01", "2027-02",
        })
        self.assertTrue((result.forecast_rain_anomaly_mm > 0).all())


class MonthlySamplePreparationTests(SimpleTestCase):
    def test_uses_only_observations_before_the_issue_month(self):
        dates = pd.date_range("2010-01-01", "2025-12-31")
        history = pd.DataFrame(
            {
                "county_name": "Test County",
                "alignment_date": dates,
                "precipitation_max_mm": 1.0,
                "soil_wetness_mean_fraction": 0.2,
                "label_evidence_basis": "NO_DOCUMENTED_EVENT",
            }
        )
        history.loc[
            history.alignment_date.dt.month.eq(12)
            & history.alignment_date.dt.year.isin([2012, 2018]),
            "label_evidence_basis",
        ] = "DOCUMENTED_EMDAT_FLOOD_EVENT"
        recent_dates = pd.date_range("2026-01-01", "2026-10-31")
        recent = pd.DataFrame(
            {
                "county_name": "Test County",
                "observation_date": recent_dates,
                "precipitation_max_mm": range(1, len(recent_dates) + 1),
                "soil_wetness_mean_fraction": 0.3,
            }
        )
        forecasts = pd.DataFrame(
            [{
                "county_name": "Test County",
                "issue_month": "2026-11",
                "target_month": "2026-12",
                "lead_month": 2,
                "forecast_rain_anomaly_mm": 12.0,
            }]
        )
        samples = prepare_samples(history, recent, forecasts)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples.iloc[0].target_month, pd.Period("2026-12"))
        october_max = recent[recent.observation_date.dt.month.eq(10)][
            "precipitation_max_mm"
        ].max()
        self.assertEqual(samples.iloc[0].rain_1m, october_max)
        self.assertTrue(pd.isna(samples.iloc[0].y))
