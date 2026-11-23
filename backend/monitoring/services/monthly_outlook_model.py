"""Leakage-safe county flood outlook trained at the displayed forecast leads."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


OBSERVED_FIELDS = ["precipitation_max_mm", "soil_wetness_mean_fraction"]
LAG_FEATURES = [
    f"{name}_{window}m"
    for name in ("rain", "soil")
    for window in (1, 3, 6)
]
MODEL_FEATURES = LAG_FEATURES + [
    "seasonal_prior",
    "forecast_rain_anomaly_mm",
    "target_month_sin",
    "target_month_cos",
]


class MonthlyOutlookModelError(RuntimeError):
    """Raised when the outlook cannot be evaluated or published safely."""


def _monthly_observations(frame, date_field, *, include_labels):
    frame = frame.copy()
    frame[date_field] = pd.to_datetime(frame[date_field], errors="raise")
    frame["month"] = frame[date_field].dt.to_period("M")
    if include_labels:
        frame["recorded"] = frame["label_evidence_basis"].eq(
            "DOCUMENTED_EMDAT_FLOOD_EVENT"
        )
    else:
        frame["recorded"] = False
    return (
        frame.groupby(["county_name", "month"], as_index=False)
        .agg(
            rain=(OBSERVED_FIELDS[0], "max"),
            soil=(OBSERVED_FIELDS[1], "mean"),
            y=("recorded", "max"),
        )
        .sort_values(["county_name", "month"])
    )


def _seasonal_prior(labels, county_name, target_month, issue_year):
    available = labels[labels.month.dt.year < issue_year]
    available = available[available.month.dt.month == target_month]
    county = available[available.county_name == county_name]
    if county.empty or available.empty:
        raise MonthlyOutlookModelError(
            f"No prior labels for {county_name}, month {target_month}, before {issue_year}."
        )
    global_rate = float(available.y.mean())
    return float((county.y.sum() + 5 * global_rate) / (len(county) + 5))


def prepare_samples(history, recent_weather, seasonal_forecasts):
    required_history = {
        "county_name",
        "alignment_date",
        "label_evidence_basis",
        *OBSERVED_FIELDS,
    }
    required_weather = {"county_name", "observation_date", *OBSERVED_FIELDS}
    required_forecast = {
        "county_name",
        "issue_month",
        "target_month",
        "lead_month",
        "forecast_rain_anomaly_mm",
    }
    for name, frame, required in (
        ("history", history, required_history),
        ("weather", recent_weather, required_weather),
        ("seasonal forecast", seasonal_forecasts, required_forecast),
    ):
        missing = required - set(frame.columns)
        if missing:
            raise MonthlyOutlookModelError(
                f"The {name} file is missing: {', '.join(sorted(missing))}."
            )

    labels = _monthly_observations(history, "alignment_date", include_labels=True)
    recent = _monthly_observations(
        recent_weather, "observation_date", include_labels=False
    )
    observations = pd.concat(
        [labels[["county_name", "month", "rain", "soil"]],
         recent[["county_name", "month", "rain", "soil"]]],
        ignore_index=True,
    ).drop_duplicates(["county_name", "month"], keep="last")

    forecasts = seasonal_forecasts.copy()
    forecasts["issue_month"] = forecasts.issue_month.map(
        lambda value: pd.Period(value, freq="M")
    )
    forecasts["target_month"] = forecasts.target_month.map(
        lambda value: pd.Period(value, freq="M")
    )
    forecasts["lead_month"] = forecasts.lead_month.astype(int)
    if forecasts.duplicated(
        ["county_name", "issue_month", "target_month", "lead_month"]
    ).any():
        raise MonthlyOutlookModelError("Duplicate issue-time seasonal forecasts.")

    label_lookup = labels.set_index(["county_name", "month"]).y
    rows = []
    for forecast in forecasts.itertuples(index=False):
        county_weather = observations[
            (observations.county_name == forecast.county_name)
            & (observations.month < forecast.issue_month)
        ].sort_values("month")
        expected = pd.period_range(
            forecast.issue_month - 6, forecast.issue_month - 1, freq="M"
        )
        tail = county_weather[county_weather.month.isin(expected)]
        if list(tail.month) != list(expected):
            continue
        row = {
            "county_name": forecast.county_name,
            "issue_month": forecast.issue_month,
            "target_month": forecast.target_month,
            "lead_month": forecast.lead_month,
            "forecast_rain_anomaly_mm": float(
                forecast.forecast_rain_anomaly_mm
            ),
            "seasonal_prior": _seasonal_prior(
                labels,
                forecast.county_name,
                forecast.target_month.month,
                forecast.issue_month.year,
            ),
            "target_month_sin": math.sin(
                2 * math.pi * forecast.target_month.month / 12
            ),
            "target_month_cos": math.cos(
                2 * math.pi * forecast.target_month.month / 12
            ),
        }
        for field in ("rain", "soil"):
            for window in (1, 3, 6):
                row[f"{field}_{window}m"] = float(tail[field].tail(window).mean())
        row["y"] = label_lookup.get(
            (forecast.county_name, forecast.target_month), np.nan
        )
        rows.append(row)
    samples = pd.DataFrame.from_records(rows)
    if samples.empty or not np.isfinite(samples[MODEL_FEATURES]).all().all():
        raise MonthlyOutlookModelError("No complete monthly forecast samples were produced.")
    return samples.sort_values(
        ["target_month", "lead_month", "county_name"]
    ).reset_index(drop=True)


def _legacy_scores(train, test):
    features = LAG_FEATURES + ["seasonal_prior"]
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=2000, random_state=42),
    )
    model.fit(train[features], train.y.astype(int))
    adjusted = model.predict_proba(test[features])[:, 1]
    return 0.9 * test.seasonal_prior.to_numpy() + 0.1 * adjusted


def _forecast_model():
    forest = RandomForestClassifier(
        n_estimators=500,
        max_depth=8,
        min_samples_leaf=4,
        max_features="sqrt",
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=-1,
    )
    return CalibratedClassifierCV(forest, method="sigmoid", cv=3)


def _top_budget_counts(frame, scores, budget=3):
    evaluated = frame[["target_month", "y"]].copy()
    evaluated["score"] = scores
    selected = evaluated.groupby("target_month", group_keys=False).apply(
        lambda group: group.nlargest(budget, "score"),
        include_groups=False,
    )
    positives = int(evaluated.y.sum())
    caught = int(selected.y.sum())
    return {
        "recorded_flood_months": positives,
        "caught": caught,
        "missed": positives - caught,
        "flags_without_matching_record": int(len(selected) - caught),
    }


def evaluate_models(samples, *, test_years=(2023, 2024, 2025)):
    labelled = samples.dropna(subset=["y"]).copy()
    labelled["y"] = labelled.y.astype(int)
    results = []
    predictions = []
    for lead in (2, 3, 4):
        lead_rows = labelled[labelled.lead_month == lead]
        for year in test_years:
            train = lead_rows[lead_rows.target_month.dt.year < year]
            test = lead_rows[lead_rows.target_month.dt.year == year]
            if test.empty or train.y.nunique() != 2 or int(train.y.sum()) < 6:
                continue
            legacy = _legacy_scores(train, test)
            model = _forecast_model()
            model.fit(train[MODEL_FEATURES], train.y)
            forecast = model.predict_proba(test[MODEL_FEATURES])[:, 1]
            fold = test[["county_name", "target_month", "lead_month", "y"]].copy()
            fold["legacy_score"] = legacy
            fold["forecast_score"] = forecast
            fold["test_year"] = year
            predictions.append(fold)
    if not predictions:
        raise MonthlyOutlookModelError("No chronological evaluation folds were available.")
    predictions = pd.concat(predictions, ignore_index=True)
    for lead, frame in predictions.groupby("lead_month"):
        row = {
            "lead_from_issue_month": int(lead),
            "test_years": sorted(frame.test_year.unique().tolist()),
            "legacy_average_precision": float(
                average_precision_score(frame.y, frame.legacy_score)
            ),
            "forecast_average_precision": float(
                average_precision_score(frame.y, frame.forecast_score)
            ),
            "legacy_brier_score": float(
                brier_score_loss(frame.y, frame.legacy_score)
            ),
            "forecast_brier_score": float(
                brier_score_loss(frame.y, frame.forecast_score)
            ),
            "legacy_review_budget": _top_budget_counts(
                frame, frame.legacy_score.to_numpy()
            ),
            "forecast_review_budget": _top_budget_counts(
                frame, frame.forecast_score.to_numpy()
            ),
        }
        results.append(row)
    accepted = all(
        row["forecast_average_precision"] >= row["legacy_average_precision"]
        and row["forecast_review_budget"]["caught"]
        >= row["legacy_review_budget"]["caught"]
        for row in results
    )
    return {"accepted": accepted, "leads": results}, predictions


def fit_current_release(samples, *, issue_month):
    labelled = samples.dropna(subset=["y"]).copy()
    labelled["y"] = labelled.y.astype(int)
    current = samples[samples.issue_month == issue_month]
    expected_targets = {issue_month + offset for offset in (1, 2, 3)}
    if set(current.target_month) != expected_targets:
        raise MonthlyOutlookModelError(
            "Seasonal data does not cover all three future target months."
        )
    publication = {}
    for lead, test in current.groupby("lead_month"):
        train = labelled[labelled.lead_month == lead]
        if train.y.nunique() != 2:
            raise MonthlyOutlookModelError(f"Lead {lead} has only one training class.")
        model = _forecast_model()
        model.fit(train[MODEL_FEATURES], train.y)
        scores = model.predict_proba(test[MODEL_FEATURES])[:, 1]
        target = str(test.target_month.iloc[0])
        publication[target] = dict(zip(test.county_name, map(float, scores)))
    return publication


def write_evaluation(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(path)
