import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse


class CountySelectorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="county-selector-user",
            email="county-selector@example.com",
            password="Temporary-Test-Only-47!",
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_dashboard_contains_accessible_county_controls(self):
        response = self.client.get(
            reverse("monitoring-web:dashboard")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'data-county-selector',
        )
        self.assertContains(
            response,
            'aria-describedby="county-selector-help"',
        )
        self.assertContains(
            response,
            'data-county-reset',
        )
        self.assertContains(
            response,
            'data-county-risk-card',
        )
        self.assertContains(
            response,
            'aria-live="polite"',
        )

    def test_geojson_contains_47_unique_named_counties(self):
        geojson_path = finders.find(
            "monitoring/data/kenya_adm1.geojson"
        )

        self.assertIsNotNone(geojson_path)

        boundary_data = json.loads(
            Path(geojson_path).read_text(
                encoding="utf-8-sig"
            )
        )

        county_names = [
            feature["properties"]["shapeName"]
            for feature in boundary_data["features"]
        ]

        self.assertEqual(
            boundary_data["type"],
            "FeatureCollection",
        )
        self.assertEqual(len(county_names), 47)
        self.assertEqual(len(set(county_names)), 47)
        self.assertIn("Nairobi", county_names)
        self.assertIn("Mombasa", county_names)

    def test_selector_populates_from_boundary_data(self):
        script_path = finders.find(
            "monitoring/js/risk_map.js"
        )

        self.assertIsNotNone(script_path)

        script = Path(script_path).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "boundaryFeatures.sort",
            script,
        )
        self.assertIn(
            'allCountiesOption.textContent = "All counties"',
            script,
        )
        self.assertIn(
            "countySelector.appendChild(option)",
            script,
        )
        self.assertIn(
            "countySelector.disabled = false",
            script,
        )

    def test_selector_supports_zoom_click_and_reset(self):
        script_path = finders.find(
            "monitoring/js/risk_map.js"
        )

        self.assertIsNotNone(script_path)

        script = Path(script_path).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'layer.on("click"',
            script,
        )
        self.assertIn(
            "selectCounty(countyKey)",
            script,
        )
        self.assertIn(
            "map.fitBounds(selectedEntry.layer.getBounds()",
            script,
        )
        self.assertIn(
            'resetButton.addEventListener("click"',
            script,
        )
        self.assertIn(
            "riskCard.hidden = true",
            script,
        )