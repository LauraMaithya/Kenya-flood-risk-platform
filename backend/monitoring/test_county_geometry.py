from django.test import SimpleTestCase

from monitoring.services.county_geometry import (
    CountyGeometryError,
    load_county_points,
    load_county_sample_points,
    normalize_county_name,
)


class CountyGeometryTests(SimpleTestCase):
    def test_county_name_normalization(self):
        examples = {
            "Elgeyo-Marakwet": "elgeyomarakwet",
            "Homa Bay": "homabay",
            "Murang'a": "muranga",
            "Tharaka": "tharakanithi",
            "Tharaka-Nithi": "tharakanithi",
        }

        for county_name, expected in examples.items():
            with self.subTest(county=county_name):
                self.assertEqual(
                    normalize_county_name(county_name),
                    expected,
                )

    def test_all_county_boundaries_have_points(self):
        county_points = load_county_points()

        self.assertEqual(len(county_points), 47)
        self.assertIn("nairobi", county_points)
        self.assertIn("turkana", county_points)
        self.assertIn("tharakanithi", county_points)

    def test_representative_points_are_within_kenya_extent(self):
        county_points = load_county_points()

        for county_key, point in county_points.items():
            with self.subTest(county=county_key):
                self.assertGreaterEqual(
                    point["latitude"],
                    -5.0,
                )
                self.assertLessEqual(
                    point["latitude"],
                    6.0,
                )
                self.assertGreaterEqual(
                    point["longitude"],
                    33.0,
                )
                self.assertLessEqual(
                    point["longitude"],
                    42.5,
                )

    def test_county_point_loading_is_cached(self):
        first = load_county_points()
        second = load_county_points()

        self.assertIs(first, second)

    def test_three_sample_points_are_derived_per_county(self):
        counties = load_county_sample_points(
            count=3
        )

        self.assertEqual(len(counties), 47)

        for county_key, county in counties.items():
            with self.subTest(county=county_key):
                self.assertEqual(
                    len(county["points"]),
                    3,
                )
                self.assertEqual(
                    len(set(county["points"])),
                    3,
                )

    def test_sample_points_are_within_kenya_extent(self):
        counties = load_county_sample_points(
            count=3
        )

        for county_key, county in counties.items():
            for longitude, latitude in county["points"]:
                with self.subTest(
                    county=county_key,
                    longitude=longitude,
                    latitude=latitude,
                ):
                    self.assertGreaterEqual(
                        latitude,
                        -5.0,
                    )
                    self.assertLessEqual(
                        latitude,
                        6.0,
                    )
                    self.assertGreaterEqual(
                        longitude,
                        33.0,
                    )
                    self.assertLessEqual(
                        longitude,
                        42.5,
                    )

    def test_nonpositive_sample_count_is_rejected(self):
        with self.assertRaisesRegex(
            CountyGeometryError,
            "must be positive",
        ):
            load_county_sample_points(count=0)