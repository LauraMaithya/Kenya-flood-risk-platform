from io import StringIO

from django.core.management import (
    CommandError,
    call_command,
)
from django.test import TestCase

from monitoring.models import County


class CountyCoordinateCommandTests(TestCase):
    def create_county(self, *, code, name, slug):
        return County.objects.create(
            code=code,
            name=name,
            slug=slug,
        )

    def test_command_populates_existing_county_coordinates(self):
        nairobi = self.create_county(
            code="047",
            name="Nairobi",
            slug="nairobi",
        )
        tharaka = self.create_county(
            code="013",
            name="Tharaka-Nithi",
            slug="tharaka-nithi",
        )
        output = StringIO()

        call_command(
            "sync_county_coordinates",
            stdout=output,
        )

        nairobi.refresh_from_db()
        tharaka.refresh_from_db()

        self.assertIsNotNone(nairobi.latitude)
        self.assertIsNotNone(nairobi.longitude)
        self.assertIsNotNone(tharaka.latitude)
        self.assertIsNotNone(tharaka.longitude)
        self.assertIn(
            "2 existing counties matched",
            output.getvalue(),
        )
        self.assertIn(
            "45 boundary-only counties left unchanged",
            output.getvalue(),
        )

    def test_dry_run_does_not_save_coordinates(self):
        nairobi = self.create_county(
            code="047",
            name="Nairobi",
            slug="nairobi",
        )
        output = StringIO()

        call_command(
            "sync_county_coordinates",
            "--dry-run",
            stdout=output,
        )

        nairobi.refresh_from_db()

        self.assertIsNone(nairobi.latitude)
        self.assertIsNone(nairobi.longitude)
        self.assertIn(
            "1 would be updated",
            output.getvalue(),
        )

    def test_unmatched_existing_county_is_rejected(self):
        self.create_county(
            code="999",
            name="Unknown Test County",
            slug="unknown-test-county",
        )

        with self.assertRaisesRegex(
            CommandError,
            "Existing counties without matching boundaries",
        ):
            call_command(
                "sync_county_coordinates",
            )