import csv
from datetime import date, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from monitoring.models import County, EnvironmentalObservation
from monitoring.services.nasa_power_refresh import (
    NasaPowerRefreshError,
    extract_nasa_power_county_days,
)


class Command(BaseCommand):
    help = "Export complete May–October 2026 NASA POWER outlook inputs without saving observations."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True, type=Path)

    def handle(self, *args, **options):
        output = options["output"]
        if output.exists():
            raise CommandError("Output already exists. Choose a new filename.")

        start, end = date(2026, 5, 1), date(2026, 10, 31)
        days = {start + timedelta(days=i) for i in range((end - start).days + 1)}
        counties = list(County.objects.filter(has_nasa_power_coverage=True).order_by("code"))
        if len(counties) != 34:
            raise CommandError(f"Expected 34 covered counties; found {len(counties)}.")

        fields = ("precipitation_max_mm", "soil_wetness_mean_fraction")
        rows = []
        for county in counties:
            observed = {}
            for day, rain, soil in EnvironmentalObservation.objects.filter(
                county=county,
                source=EnvironmentalObservation.Source.NASA_POWER,
                is_synthetic=False,
                observation_date__range=(start, end),
            ).values_list("observation_date", *fields):
                if rain is not None and soil is not None:
                    if day in observed:
                        raise CommandError(f"Duplicate NASA POWER row: {county.name}, {day}.")
                    observed[day] = (rain, soil)

            missing = days - observed.keys()
            if any(day.month != 10 for day in missing):
                raise CommandError(f"{county.name} has missing inputs before October.")
            if missing:
                self.stdout.write(f"Recovering {len(missing)} date(s) for {county.name}…")
                try:
                    retrieved, _ = extract_nasa_power_county_days(
                        county, start_date=min(missing), end_date=max(missing),
                        sample_point_count=3, timeout=60,
                    )
                except NasaPowerRefreshError as exc:
                    raise CommandError(str(exc)) from exc
                for record in retrieved:
                    if record.observation_date in missing and record.contributing_points == 3:
                        observed[record.observation_date] = (
                            record.precipitation_max_mm, record.soil_wetness_mean_fraction,
                        )
            if days - observed.keys():
                raise CommandError(f"Incomplete NASA POWER recovery for {county.name}.")
            rows.extend((county.code, county.name, day, *observed[day]) for day in sorted(days))

        with output.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("county_code", "county_name", "observation_date", *fields))
            writer.writerows(rows)
        self.stdout.write(self.style.SUCCESS(f"Exported {len(rows)} county-days to {output}."))
