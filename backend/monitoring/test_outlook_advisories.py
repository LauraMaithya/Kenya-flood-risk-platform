from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from monitoring.models import (
    AlertNotification,
    County,
    MonthlyOutlookAdvisory,
)
from monitoring.services.outlook_advisories import (
    create_outlook_advisories,
)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ALERT_EMAIL_RECIPIENTS=["redcross@example.com"],
    IN_APP_ALERT_RECIPIENT="platform-users",
    OUTLOOK_ADVISORY_THRESHOLD=0.15,
    OUTLOOK_ADVISORY_CHANGE_THRESHOLD=0.05,
)
class OutlookAdvisoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.county = County.objects.create(
            code="047",
            name="Nairobi",
            slug="nairobi",
            latitude=Decimal("-1.286389"),
            longitude=Decimal("36.817223"),
            has_nasa_power_coverage=True,
        )
        cls.user = get_user_model().objects.create_user(
            username="outlook-operator",
            password="M7!qZ9#vR2@kL8$x",
        )

    def scores(self, probability):
        return {"2027-01": {"Nairobi": probability}}

    def test_qualifying_release_creates_in_app_and_email(self):
        summary = create_outlook_advisories(
            scores=self.scores(0.20),
            issued_on=date(2026, 11, 22),
        )
        self.assertEqual(summary.qualifying_county_months, 1)
        self.assertEqual(summary.advisories_created, 2)
        self.assertEqual(summary.emails_sent, 1)
        self.assertEqual(MonthlyOutlookAdvisory.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("not a live flood warning", mail.outbox[0].body)

    def test_below_threshold_release_creates_nothing(self):
        summary = create_outlook_advisories(
            scores=self.scores(0.149),
            issued_on=date(2026, 11, 22),
        )
        self.assertEqual(summary.qualifying_county_months, 0)
        self.assertEqual(MonthlyOutlookAdvisory.objects.count(), 0)

    def test_repeat_is_idempotent(self):
        kwargs = {
            "scores": self.scores(0.20),
            "issued_on": date(2026, 11, 22),
        }
        create_outlook_advisories(**kwargs)
        second = create_outlook_advisories(**kwargs)
        self.assertEqual(second.advisories_created, 0)
        self.assertEqual(second.advisories_existing, 2)
        self.assertEqual(MonthlyOutlookAdvisory.objects.count(), 2)

    def test_later_release_requires_material_increase(self):
        create_outlook_advisories(
            scores=self.scores(0.20),
            issued_on=date(2026, 11, 1),
        )
        small_change = create_outlook_advisories(
            scores=self.scores(0.24),
            issued_on=date(2026, 11, 22),
        )
        self.assertEqual(small_change.advisories_created, 0)
        material_change = create_outlook_advisories(
            scores=self.scores(0.25),
            issued_on=date(2026, 11, 23),
        )
        self.assertEqual(material_change.advisories_created, 2)

    def test_advisory_appears_and_can_be_acknowledged(self):
        create_outlook_advisories(
            scores=self.scores(0.20),
            issued_on=date(2026, 11, 22),
        )
        advisory = MonthlyOutlookAdvisory.objects.get(
            channel=AlertNotification.Channel.IN_APP
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("monitoring-web:alerts"))
        self.assertContains(response, "Months-ahead outlook advisories")
        self.assertContains(response, "20.0%")
        response = self.client.post(
            reverse(
                "monitoring-web:outlook-advisory-acknowledge",
                kwargs={"pk": advisory.pk},
            )
        )
        self.assertRedirects(response, reverse("monitoring-web:alerts"))
        advisory.refresh_from_db()
        self.assertIsNotNone(advisory.acknowledged_at)
