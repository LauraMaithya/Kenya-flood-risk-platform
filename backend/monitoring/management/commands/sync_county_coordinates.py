from decimal import Decimal

from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.db import transaction

from monitoring.models import County
from monitoring.services.county_geometry import (
    CountyGeometryError,
    load_county_points,
    normalize_county_name,
)


COORDINATE_PRECISION = Decimal("0.000001")


def _coordinate_decimal(value):
    return Decimal(str(value)).quantize(
        COORDINATE_PRECISION
    )


class Command(BaseCommand):
    help = (
        "Populate representative coordinates for existing counties "
        "from the bundled Kenya ADM1 GeoJSON file."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Validate county matching without saving coordinates."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        try:
            boundary_points = load_county_points()
        except CountyGeometryError as exc:
            raise CommandError(str(exc)) from exc

        counties = list(
            County.objects.order_by("name")
        )
        unmatched_counties = []
        updates = []

        for county in counties:
            county_key = normalize_county_name(
                county.name
            )
            point = boundary_points.get(county_key)

            if point is None:
                unmatched_counties.append(county.name)
                continue

            latitude = _coordinate_decimal(
                point["latitude"]
            )
            longitude = _coordinate_decimal(
                point["longitude"]
            )

            if (
                county.latitude == latitude
                and county.longitude == longitude
            ):
                continue

            updates.append(
                (
                    county,
                    latitude,
                    longitude,
                )
            )

        if unmatched_counties:
            names = ", ".join(unmatched_counties)
            raise CommandError(
                "Existing counties without matching boundaries: "
                f"{names}"
            )

        if not dry_run:
            for county, latitude, longitude in updates:
                county.latitude = latitude
                county.longitude = longitude
                county.full_clean()
                county.save(
                    update_fields=[
                        "latitude",
                        "longitude",
                        "updated_at",
                    ]
                )

        matched_count = len(counties)
        boundary_only_count = (
            len(boundary_points) - matched_count
        )
        action = (
            "would be updated"
            if dry_run
            else "updated"
        )

        self.stdout.write(
            self.style.SUCCESS(
                "County coordinate sync completed: "
                f"{matched_count} existing counties matched, "
                f"{len(updates)} {action}, "
                f"{boundary_only_count} boundary-only counties "
                "left unchanged."
            )
        )