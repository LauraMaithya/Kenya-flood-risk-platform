"""Download and normalise issue-time C3S seasonal rainfall anomalies."""

from __future__ import annotations

import calendar
import json
import math
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

import numpy as np
import pandas as pd
import xarray as xr


DATASET = "seasonal-postprocessed-single-levels"
MODEL_CENTRE = "ecmwf"
MODEL_SYSTEM = "51"
LEADS = (2, 3, 4)
KENYA_AREA = [5, 33, -5, 42]


class SeasonalForecastError(RuntimeError):
    """Raised when a C3S response cannot be safely used."""


def _coordinate_name(values, candidates):
    lowered = {str(name).lower(): name for name in values}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def _lead_number(value):
    if isinstance(value, np.timedelta64):
        return int(round(value / np.timedelta64(30, "D")))
    try:
        return int(value)
    except (TypeError, ValueError):
        text = str(value).lower().replace("months", "").replace("month", "")
        digits = "".join(character for character in text if character.isdigit())
        return int(digits) if digits else None


def _rainfall_anomaly_mm(value, units, target_year, target_month):
    units = (units or "").lower().replace(" ", "")
    days = calendar.monthrange(target_year, target_month)[1]
    if "s-1" in units or "s**-1" in units or "/s" in units:
        return value * 1000 * 86400 * days
    if units in {"m", "metre", "meter"}:
        return value * 1000
    return value


def _data_variable(dataset):
    candidates = []
    for name, variable in dataset.data_vars.items():
        lowered = name.lower()
        if "precip" in lowered or lowered in {"tpara", "tprate", "tp"}:
            candidates.append((0, name))
        elif np.issubdtype(variable.dtype, np.number):
            candidates.append((1, name))
    if not candidates:
        raise SeasonalForecastError("No numeric precipitation anomaly was found in the C3S file.")
    return dataset[sorted(candidates)[0][1]]


def normalise_c3s_files(paths, *, issue_month=None, county_locations):
    """Return one county row per issue year and lead from C3S NetCDF files."""
    records = []
    for path in paths:
        if Path(path).suffix.lower() in {".grib", ".grb", ".grib2"}:
            records.extend(
                _normalise_grib_file(
                    path,
                    issue_month=issue_month,
                    county_locations=county_locations,
                )
            )
            continue
        with xr.open_dataset(path) as dataset:
            variable = _data_variable(dataset)
            latitude = _coordinate_name(variable.coords, ("latitude", "lat"))
            longitude = _coordinate_name(variable.coords, ("longitude", "lon"))
            lead_name = _coordinate_name(
                variable.coords,
                ("forecastMonth", "leadtime_month", "fcmonth", "leadtime"),
            )
            issue_name = _coordinate_name(
                variable.coords,
                ("forecast_reference_time", "forecast_time", "time", "date"),
            )
            if not all((latitude, longitude, lead_name, issue_name)):
                raise SeasonalForecastError(
                    f"Unsupported C3S coordinates in {Path(path).name}: "
                    f"{list(variable.coords)}"
                )

            issue_values = np.atleast_1d(variable.coords[issue_name].values)
            lead_values = np.atleast_1d(variable.coords[lead_name].values)
            for issue_index, issue_value in enumerate(issue_values):
                issue_date = pd.Timestamp(issue_value)
                issue = pd.Period(
                    year=issue_date.year,
                    month=issue_month or issue_date.month,
                    freq="M",
                )
                issue_field = variable
                if issue_name in variable.dims:
                    issue_field = issue_field.isel({issue_name: issue_index})
                for lead_index, raw_lead in enumerate(lead_values):
                    lead = _lead_number(raw_lead)
                    if lead not in LEADS:
                        continue
                    field = issue_field
                    if lead_name in field.dims:
                        field = field.isel({lead_name: lead_index})
                    target = issue + lead - 1
                    for county_name, coordinates in county_locations.items():
                        county_latitude, county_longitude = coordinates
                        point = field.sel(
                            {
                                latitude: county_latitude,
                                longitude: county_longitude,
                            },
                            method="nearest",
                        )
                        value = float(np.asarray(point.values).mean())
                        value = _rainfall_anomaly_mm(
                            value,
                            variable.attrs.get("units"),
                            target.year,
                            target.month,
                        )
                        if not math.isfinite(value):
                            raise SeasonalForecastError("C3S returned a non-finite rainfall anomaly.")
                        records.append(
                            {
                                "county_name": county_name,
                                "issue_month": str(issue),
                                "target_month": str(target),
                                "lead_month": lead,
                                "forecast_rain_anomaly_mm": value,
                            }
                        )
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        raise SeasonalForecastError("C3S files contained no supported forecast rows.")
    frame = frame.drop_duplicates(
        ["county_name", "issue_month", "target_month", "lead_month"],
        keep="last",
    )
    return frame.sort_values(
        ["issue_month", "lead_month", "county_name"]
    ).reset_index(drop=True)


def _normalise_grib_file(path, *, issue_month, county_locations):
    try:
        from eccodes import (
            codes_get,
            codes_get_array,
            codes_grib_new_from_file,
            codes_release,
        )
    except ImportError as exc:
        raise SeasonalForecastError(
            "Install requirements.txt before reading native C3S GRIB data."
        ) from exc

    records = []
    with Path(path).open("rb") as stream:
        while True:
            message = codes_grib_new_from_file(stream)
            if message is None:
                break
            try:
                issue_date = str(codes_get(message, "dataDate"))
                issue = pd.Period(
                    year=int(issue_date[:4]),
                    month=issue_month or int(issue_date[4:6]),
                    freq="M",
                )
                lead = int(codes_get(message, "forecastMonth"))
                if lead not in LEADS:
                    continue
                target = issue + lead - 1
                latitudes = np.asarray(codes_get_array(message, "latitudes"))
                longitudes = np.asarray(codes_get_array(message, "longitudes"))
                values = np.asarray(codes_get_array(message, "values"))
                units = str(codes_get(message, "units"))
                for county_name, coordinates in county_locations.items():
                    county_latitude, county_longitude = coordinates
                    distances = (
                        (latitudes - county_latitude) ** 2
                        + (longitudes - county_longitude) ** 2
                    )
                    value = float(values[int(np.argmin(distances))])
                    value = _rainfall_anomaly_mm(
                        value, units, target.year, target.month
                    )
                    if not math.isfinite(value):
                        raise SeasonalForecastError(
                            "C3S returned a non-finite rainfall anomaly."
                        )
                    records.append(
                        {
                            "county_name": county_name,
                            "issue_month": str(issue),
                            "target_month": str(target),
                            "lead_month": lead,
                            "forecast_rain_anomaly_mm": value,
                        }
                    )
            finally:
                codes_release(message)
    if not records:
        raise SeasonalForecastError(
            f"No supported seasonal messages were found in {Path(path).name}."
        )
    return records


def _forecast_paths(download, directory):
    download = Path(download)
    if zipfile.is_zipfile(download):
        extract_to = Path(directory) / download.stem
        extract_to.mkdir()
        with zipfile.ZipFile(download) as archive:
            archive.extractall(extract_to)
        paths = sorted(
            path
            for path in extract_to.rglob("*")
            if path.is_file()
            and path.suffix.lower() in {".nc", ".grib", ".grb", ".grib2"}
        )
    else:
        paths = [download]
    if not paths:
        raise SeasonalForecastError(
            "The C3S download did not contain a supported GRIB or NetCDF file."
        )
    return paths


def download_c3s_archive(output_path, *, county_locations, start_year, through):
    """Download issue-time rainfall anomalies and atomically update a CSV cache."""
    try:
        import cdsapi
    except ImportError as exc:
        raise SeasonalForecastError("Install requirements.txt before downloading C3S data.") from exc

    output_path = Path(output_path)
    metadata_path = output_path.with_suffix(".metadata.json")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        cached_through = date.fromisoformat(metadata["through"])
        if (
            output_path.is_file()
            and (cached_through.year, cached_through.month)
            == (through.year, through.month)
        ):
            return pd.read_csv(output_path)
    except (OSError, ValueError, KeyError, TypeError):
        pass

    if not county_locations or any(
        latitude is None or longitude is None
        for latitude, longitude in county_locations.values()
    ):
        raise SeasonalForecastError("Every outlook county requires latitude and longitude.")

    client = cdsapi.Client(timeout=900)
    frames = []
    parts_directory = output_path.with_name(output_path.stem + "-parts")
    parts_directory.mkdir(parents=True, exist_ok=True)
    request_groups = []
    complete_years = [
        str(year) for year in range(start_year, through.year)
    ]
    if complete_years:
        request_groups.append(
            (
                f"archive-{start_year}-{through.year - 1}",
                complete_years,
                [f"{month:02d}" for month in range(1, 13)],
            )
        )
    if through.year >= start_year:
        request_groups.append(
            (
                f"current-{through.year}-through-{through.month:02d}",
                [str(through.year)],
                [f"{month:02d}" for month in range(1, through.month + 1)],
            )
        )

    with TemporaryDirectory(prefix="kfr-c3s-") as temporary:
        temporary = Path(temporary)
        for label, years, months in request_groups:
            part = parts_directory / f"{label}.csv"
            if part.is_file():
                frames.append(pd.read_csv(part))
                continue
            target = temporary / f"{label}.grib"
            request = {
                "originating_centre": MODEL_CENTRE,
                "system": MODEL_SYSTEM,
                "variable": "total_precipitation_anomalous_rate_of_accumulation",
                "product_type": "ensemble_mean",
                "year": years,
                "month": months,
                "leadtime_month": [str(value) for value in LEADS],
                "area": KENYA_AREA,
                "data_format": "grib",
            }
            try:
                client.retrieve(DATASET, request, str(target))
            except Exception as exc:
                raise SeasonalForecastError(
                    f"C3S download failed for {label}: {exc}"
                ) from exc
            group_frame = normalise_c3s_files(
                _forecast_paths(target, temporary),
                county_locations=county_locations,
            )
            part_temporary = part.with_suffix(".tmp")
            group_frame.to_csv(part_temporary, index=False)
            part_temporary.replace(part)
            frames.append(group_frame)

    result = pd.concat(frames, ignore_index=True)
    keys = ["county_name", "issue_month", "target_month", "lead_month"]
    if result.duplicated(keys).any():
        raise SeasonalForecastError("C3S cache contains duplicate county forecasts.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp")
    result.to_csv(temporary, index=False)
    temporary.replace(output_path)
    metadata = {
        "dataset": DATASET,
        "originating_centre": MODEL_CENTRE,
        "system": MODEL_SYSTEM,
        "leads": list(LEADS),
        "through": through.isoformat(),
        "rows": len(result),
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return result
