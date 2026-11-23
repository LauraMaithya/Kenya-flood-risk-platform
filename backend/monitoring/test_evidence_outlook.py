from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from monitoring.services.evidence_outlook import (
    EvidenceOutlookError,
    MODEL_FEATURES,
    _supported_high_threshold,
    build_samples,
    validate_release_sanity,
)
from monitoring.services.outlook_publication import publish_outlook


def monthly_history():
    rows = []
    for county_index, county in enumerate(("Alpha", "Beta")):
        for month in pd.period_range("2010-01", "2025-12", freq="M"):
            seasonal = month.month * 2 + county_index
            rows.append(
                {
                    "county_name": county,
                    "month": month,
                    "rain_sum": float(50 + seasonal),
                    "rain_max": float(10 + seasonal),
                    "soil_mean": float(0.2 + month.month / 100),
                    "soil_max": float(0.3 + month.month / 100),
                    "high_days": int(month.month in {4, 5, 11}),
                    "emdat_days": 0,
                    "observed_days": month.days_in_month,
                }
            )
    return pd.DataFrame.from_records(rows)


class EvidenceSampleTests(SimpleTestCase):
    def test_lead_features_stop_at_the_issue_month(self):
        samples = build_samples(monthly_history(), target_days=7)
        row = samples[
            samples.county_name.eq("Alpha")
            & samples.month.eq(pd.Period("2025-12"))
            & samples.lead.eq(2)
        ].iloc[0]
        self.assertEqual(row.issue_month, pd.Period("2025-10"))
        self.assertEqual(row.rain_sum_1m, 70.0)
        self.assertTrue(np.isfinite(row[list(MODEL_FEATURES)].astype(float)).all())

    def test_issue_month_normals_are_kept_separate_from_target_normals(self):
        samples = build_samples(monthly_history(), target_days=7)
        row = samples[
            samples.county_name.eq("Alpha")
            & samples.month.eq(pd.Period("2025-12"))
            & samples.lead.eq(2)
        ].iloc[0]

        self.assertEqual(row.issue_month, pd.Period("2025-10"))
        self.assertEqual(row.issue_rain_sum, 70.0)
        self.assertNotEqual(
            row.issue_rain_sum_normal,
            row.rain_sum_normal,
        )

    def test_high_band_is_withheld_without_validation_precision(self):
        y_true = np.array([1, 0, 0, 0])
        scores = np.array([0.1, 0.4, 0.3, 0.2])
        threshold, supported = _supported_high_threshold(y_true, scores)
        self.assertFalse(supported)
        self.assertGreater(threshold, scores.max())


class EvidencePublicationTests(SimpleTestCase):
    def test_rejects_collapsed_release_without_changing_scores(self):
        scores = {
            "2027-01": {
                "Alpha": 0.176,
                "Beta": 0.177,
            }
        }
        details = {
            "2027-01": {
                county: {"band": "Medium"} for county in scores["2027-01"]
            }
        }

        with self.assertRaisesMessage(
            EvidenceOutlookError,
            "scores collapsed",
        ):
            validate_release_sanity(scores, details)

        self.assertEqual(scores["2027-01"]["Alpha"], 0.176)

    def test_accepts_differentiated_release(self):
        scores = {
            "2027-01": {
                "Alpha": 0.12,
                "Beta": 0.42,
            }
        }
        details = {
            "2027-01": {
                "Alpha": {"band": "Low"},
                "Beta": {"band": "Medium"},
            }
        }

        validate_release_sanity(scores, details)

    def test_persists_thresholds_and_explanations(self):
        counties = {"Alpha", "Beta"}
        scores = {
            month: {county: 0.2 for county in counties}
            for month in ("2026-12", "2027-01", "2027-02")
        }
        details = {
            month: {
                county: {"band": "Medium", "why": "Test evidence"}
                for county in counties
            }
            for month in scores
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "outlook-current.json"
            publish_outlook(
                path,
                issued_on=date(2026, 11, 23),
                observed_through=date(2026, 10, 31),
                scores=scores,
                county_names=counties,
                thresholds={"2": {"high": 0.4, "medium": 0.1}},
                details=details,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["details"]["2026-12"]["Alpha"]["band"], "Medium")
        self.assertEqual(payload["thresholds"]["2"]["high"], 0.4)
