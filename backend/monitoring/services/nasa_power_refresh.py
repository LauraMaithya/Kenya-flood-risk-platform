from dataclasses import dataclass

from monitoring.services.county_geometry import (
    CountyGeometryError,
    load_county_sample_points,
    normalize_county_name,
)
from monitoring.services.nasa_power import (
    NasaPowerError,
    NasaPowerNoDataError,
    fetch_nasa_power_daily_point,
)
from monitoring.services.nasa_power_etl import (
    NasaPowerETLError,
    aggregate_nasa_power_points,
)
from monitoring.services.nasa_power_storage import (
    NasaPowerStorageError,
    store_nasa_power_county_days,
)


class NasaPowerRefreshError(RuntimeError):
    """Raised when a county NASA POWER refresh fails."""

class NasaPowerDataUnavailable(NasaPowerRefreshError):
    """Raised when NASA has not published the requested dates."""

@dataclass(frozen=True)
class NasaPowerRefreshSummary:
    county_code: str
    county_name: str
    requested_points: int
    county_days: int
    observations_created: int
    observations_updated: int
    observations_unchanged: int
    dry_run: bool


def refresh_nasa_power_county(
    county,
    *,
    start_date,
    end_date,
    sample_point_count=3,
    timeout=30,
    dry_run=False,
):
    if county.pk is None:
        raise NasaPowerRefreshError(
            "The county must be saved before refresh."
        )

    if not county.has_nasa_power_coverage:
        raise NasaPowerRefreshError(
            f"{county.name} is not marked for NASA POWER coverage."
        )

    try:
        county_samples = load_county_sample_points(
            count=sample_point_count
        )
    except CountyGeometryError as exc:
        raise NasaPowerRefreshError(str(exc)) from exc

    county_key = normalize_county_name(
        county.name
    )
    county_geometry = county_samples.get(
        county_key
    )

    if county_geometry is None:
        raise NasaPowerRefreshError(
            f"No county boundary matched {county.name}."
        )

    point_records = []

    for longitude, latitude in county_geometry[
        "points"
    ]:
        try:
            records = fetch_nasa_power_daily_point(
                latitude=latitude,
                longitude=longitude,
                start_date=start_date,
                end_date=end_date,
                timeout=timeout,
            )
        except NasaPowerNoDataError as exc:
            raise NasaPowerDataUnavailable(
                "NASA POWER data is not yet available for "
                f"{county.name} from {start_date} to {end_date}."
            ) from exc
        except NasaPowerError as exc:
            raise NasaPowerRefreshError(
                "NASA POWER extraction failed for "
                f"{county.name} at "
                f"{latitude:.6f}, {longitude:.6f}: {exc}"
            ) from exc

        point_records.append(records)

    try:
        county_days = aggregate_nasa_power_points(
            point_records
        )
    except NasaPowerETLError as exc:
        raise NasaPowerRefreshError(
            f"NASA POWER transformation failed for "
            f"{county.name}: {exc}"
        ) from exc

    try:
        storage = store_nasa_power_county_days(
            county,
            county_days,
            dry_run=dry_run,
        )
    except NasaPowerStorageError as exc:
        raise NasaPowerRefreshError(
            f"NASA POWER loading failed for "
            f"{county.name}: {exc}"
        ) from exc

    return NasaPowerRefreshSummary(
        county_code=county.code,
        county_name=county.name,
        requested_points=len(point_records),
        county_days=len(county_days),
        observations_created=storage.created,
        observations_updated=storage.updated,
        observations_unchanged=storage.unchanged,
        dry_run=dry_run,
    )