from dataclasses import dataclass
from datetime import date, timedelta

from monitoring.models import (
    EnvironmentalObservation,
)


class NasaPowerScheduleError(RuntimeError):
    """Raised when a safe NASA POWER refresh plan cannot be built."""


@dataclass(frozen=True)
class NasaPowerMissingRange:
    county_id: int
    county_code: str
    county_name: str
    start_date: date
    end_date: date

    @property
    def day_count(self):
        return (
            self.end_date - self.start_date
        ).days + 1


def _collapse_dates_to_ranges(
    county,
    missing_dates,
):
    if not missing_dates:
        return ()

    ranges = []
    range_start = missing_dates[0]
    previous_date = missing_dates[0]

    for current_date in missing_dates[1:]:
        if current_date != (
            previous_date + timedelta(days=1)
        ):
            ranges.append(
                NasaPowerMissingRange(
                    county_id=county.pk,
                    county_code=county.code,
                    county_name=county.name,
                    start_date=range_start,
                    end_date=previous_date,
                )
            )
            range_start = current_date

        previous_date = current_date

    ranges.append(
        NasaPowerMissingRange(
            county_id=county.pk,
            county_code=county.code,
            county_name=county.name,
            start_date=range_start,
            end_date=previous_date,
        )
    )

    return tuple(ranges)


def find_missing_nasa_power_ranges(
    county,
    *,
    start_date,
    end_date,
):
    if county.pk is None:
        raise NasaPowerScheduleError(
            "The county must be saved before planning a refresh."
        )

    if start_date > end_date:
        raise NasaPowerScheduleError(
            "NASA POWER plan start date must be on or "
            "before end date."
        )

    existing_rows = list(
        EnvironmentalObservation.objects.filter(
            county=county,
            observation_date__range=(
                start_date,
                end_date,
            ),
        ).values_list(
            "observation_date",
            "source",
        )
    )

    covered_sources = {
        EnvironmentalObservation.Source.NASA_POWER,
        EnvironmentalObservation.Source.LIVE_API_IOT,
    }

    conflicting_rows = [
        (
            observation_date,
            source,
        )
        for observation_date, source in existing_rows
        if source not in covered_sources
    ]

    if conflicting_rows:
        conflict_date, conflict_source = (
            conflicting_rows[0]
        )
        raise NasaPowerScheduleError(
            "NASA POWER planning found an existing "
            f"{conflict_source} observation for "
            f"{county.name} on {conflict_date}."
        )

    existing_dates = {
        observation_date
        for observation_date, source in existing_rows
        if source in covered_sources
    }
    requested_day_count = (
        end_date - start_date
    ).days + 1
    missing_dates = [
        start_date + timedelta(days=offset)
        for offset in range(requested_day_count)
        if (
            start_date + timedelta(days=offset)
        )
        not in existing_dates
    ]

    return _collapse_dates_to_ranges(
        county,
        missing_dates,
    )


def build_nasa_power_refresh_plan(
    counties,
    *,
    start_date,
    end_date,
):
    plan = []

    for county in counties:
        plan.extend(
            find_missing_nasa_power_ranges(
                county,
                start_date=start_date,
                end_date=end_date,
            )
        )

    return tuple(plan)