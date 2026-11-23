from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import localdate

from monitoring.models import County
from monitoring.services.monthly_outlook import EVENT_YEARS
from monitoring.services.seasonal_forecast import (
    SeasonalForecastError,
    download_c3s_archive,
)


class Command(BaseCommand):
    help = "Download bias-adjusted ECMWF seasonal rainfall anomalies for the monthly outlook."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True, type=Path)
        parser.add_argument("--start-year", default=2017, type=int)
        parser.add_argument(
            "--through",
            type=date.fromisoformat,
            default=None,
            help="Latest issue date to request (YYYY-MM-DD). Defaults to today.",
        )

    def handle(self, *args, **options):
        counties = County.objects.filter(name__in=EVENT_YEARS).values_list(
            "name", "latitude", "longitude"
        )
        locations = {
            name: (float(latitude), float(longitude))
            for name, latitude, longitude in counties
            if latitude is not None and longitude is not None
        }
        missing = sorted(set(EVENT_YEARS) - set(locations))
        if missing:
            raise CommandError(
                "Missing county coordinates: " + ", ".join(missing)
            )
        try:
            frame = download_c3s_archive(
                options["output"],
                county_locations=locations,
                start_year=options["start_year"],
                through=options["through"] or localdate(),
            )
        except SeasonalForecastError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Saved {len(frame)} issue-time county forecasts to {options['output']}."
            )
        )
