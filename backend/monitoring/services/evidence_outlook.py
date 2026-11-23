"""Chronological, evidence-based county flood outlook modelling.

The daily Random Forest is deliberately not used or changed here.  This module
aggregates its historical labels into a sustained monthly-risk target, then
trains a separate Random Forest for each displayed lead from the latest complete
observation month.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


TARGET_DAY_CANDIDATES = (5, 7, 10)
ACCEPTED_TARGET_DAYS = 7
LEADS = (2, 3, 4)
EVALUATION_YEARS = (2023, 2024, 2025)
ARID_REVIEW_COUNTIES = ("Wajir", "Mandera", "Garissa", "Marsabit", "Turkana")
COMPARISON_COUNTIES = ("Busia", "Homa Bay", "Siaya", "Tana River", "Narok")

BASE_MONTHLY_FIELDS = (
    "rain_sum",
    "rain_max",
    "soil_mean",
    "soil_max",
    "high_days",
)
ROLLING_FEATURES = tuple(
    f"{field}_{window}m"
    for field in BASE_MONTHLY_FIELDS
    for window in (1, 3, 6)
)
MODEL_FEATURES = (
    "seasonal_prior",
    "rain_sum_normal",
    "soil_mean_normal",
    "target_month_sin",
    "target_month_cos",
    "target_rain_sum_lag12",
    "target_rain_sum_lag24mean",
    "target_soil_mean_lag12",
    "target_soil_mean_lag24mean",
    "target_high_days_lag12",
    "target_high_days_lag24mean",
    "rain_anomaly",
    "soil_anomaly",
    "rain_trend3",
    "soil_trend3",
    "rain_trend6",
    "soil_trend6",
    "ytd_rain_mean",
    "ytd_soil_mean",
    *ROLLING_FEATURES,
)


class EvidenceOutlookError(RuntimeError):
    """Raised when a monthly release cannot be evaluated or published safely."""


def aggregate_history(history):
    """Aggregate real daily training records into complete county-month rows."""
    required = {
        "county_name",
        "alignment_date",
        "is_synthetic",
        "label_evidence_basis",
        "flood_risk_label",
        "precipitation_max_mm",
        "soil_wetness_mean_fraction",
        "soil_wetness_max_fraction",
    }
    missing = required - set(history.columns)
    if missing:
        raise EvidenceOutlookError(
            "Historical data is missing: " + ", ".join(sorted(missing))
        )
    frame = history.copy()
    if frame["is_synthetic"].astype(bool).any():
        raise EvidenceOutlookError("The monthly model accepts real records only.")
    frame["alignment_date"] = pd.to_datetime(
        frame["alignment_date"], errors="raise"
    )
    if frame.duplicated(["county_name", "alignment_date"]).any():
        raise EvidenceOutlookError("Duplicate historical county-days were found.")
    frame["month"] = frame.alignment_date.dt.to_period("M")
    frame["high_day"] = frame.flood_risk_label.eq("High").astype(int)
    frame["emdat_day"] = frame.label_evidence_basis.eq(
        "DOCUMENTED_EMDAT_FLOOD_EVENT"
    ).astype(int)
    monthly = (
        frame.groupby(["county_name", "month"], as_index=False)
        .agg(
            rain_sum=("precipitation_max_mm", "sum"),
            rain_max=("precipitation_max_mm", "max"),
            soil_mean=("soil_wetness_mean_fraction", "mean"),
            soil_max=("soil_wetness_max_fraction", "max"),
            high_days=("high_day", "sum"),
            emdat_days=("emdat_day", "sum"),
            observed_days=("alignment_date", "count"),
        )
        .sort_values(["county_name", "month"])
        .reset_index(drop=True)
    )
    expected_days = monthly.month.map(lambda value: value.days_in_month)
    if not monthly.observed_days.eq(expected_days).all():
        raise EvidenceOutlookError("Historical county-month coverage is incomplete.")
    return monthly, frame


def aggregate_recent(observations):
    """Aggregate recent real observations and their approved daily classifications."""
    required = {
        "county_name",
        "observation_date",
        "precipitation_max_mm",
        "soil_wetness_mean_fraction",
        "soil_wetness_max_fraction",
        "risk_level",
    }
    missing = required - set(observations.columns)
    if missing:
        raise EvidenceOutlookError(
            "Recent data is missing: " + ", ".join(sorted(missing))
        )
    frame = observations.copy()
    frame["observation_date"] = pd.to_datetime(
        frame.observation_date, errors="raise"
    )
    if frame.duplicated(["county_name", "observation_date"]).any():
        raise EvidenceOutlookError("Duplicate recent county-days were found.")
    frame["month"] = frame.observation_date.dt.to_period("M")
    frame["high_day"] = frame.risk_level.eq("High").astype(int)
    monthly = (
        frame.groupby(["county_name", "month"], as_index=False)
        .agg(
            rain_sum=("precipitation_max_mm", "sum"),
            rain_max=("precipitation_max_mm", "max"),
            soil_mean=("soil_wetness_mean_fraction", "mean"),
            soil_max=("soil_wetness_max_fraction", "max"),
            high_days=("high_day", "sum"),
            observed_days=("observation_date", "count"),
        )
        .sort_values(["county_name", "month"])
        .reset_index(drop=True)
    )
    monthly["emdat_days"] = 0
    return monthly


def latest_complete_month(recent_monthly, county_names):
    expected_counties = set(county_names)
    for month in sorted(recent_monthly.month.unique(), reverse=True):
        rows = recent_monthly[recent_monthly.month.eq(month)]
        if (
            set(rows.county_name) == expected_counties
            and rows.observed_days.eq(month.days_in_month).all()
        ):
            return month
    raise EvidenceOutlookError("No complete recent county-month is available.")


def _prior_year_feature(frame, column, periods):
    grouped = frame.groupby("county_name")[column]
    values = [grouped.shift(period) for period in periods]
    return sum(values) / len(values)


def build_samples(historical_monthly, *, target_days, recent_monthly=None):
    """Create leakage-safe lead-specific samples and optional publication rows."""
    historical = historical_monthly.copy()
    historical["is_training"] = True
    if recent_monthly is not None:
        recent = recent_monthly.copy()
        recent["is_training"] = False
        combined = pd.concat([historical, recent], ignore_index=True)
        combined = combined.drop_duplicates(
            ["county_name", "month"], keep="last"
        )
        cutoff = recent.month.max()
        future_rows = []
        for county_name in sorted(historical.county_name.unique()):
            for month in pd.period_range(cutoff + 1, cutoff + 4, freq="M"):
                future_rows.append(
                    {
                        "county_name": county_name,
                        "month": month,
                        "is_training": False,
                    }
                )
        combined = pd.concat(
            [combined, pd.DataFrame.from_records(future_rows)],
            ignore_index=True,
        ).drop_duplicates(["county_name", "month"], keep="first")
    else:
        combined = historical
    combined = combined.sort_values(["county_name", "month"]).reset_index(drop=True)
    combined["year"] = combined.month.dt.year
    combined["calendar_month"] = combined.month.dt.month
    combined["y"] = combined.high_days.ge(target_days).astype(int)

    county_season = combined.groupby(
        ["county_name", "calendar_month"], group_keys=False
    )
    training_target = combined.y.where(combined.is_training)
    prior_count = training_target.groupby(
        [combined.county_name, combined.calendar_month]
    ).transform(lambda values: values.shift(1).expanding().count())
    prior_sum = training_target.groupby(
        [combined.county_name, combined.calendar_month]
    ).transform(
        lambda values: values.shift(1).expanding(min_periods=2).sum()
    )
    yearly_global = (
        combined[combined.is_training]
        .groupby(["year", "calendar_month"])
        .y.mean()
        .sort_index()
        .groupby(level=1)
        .transform(lambda values: values.shift(1).expanding(min_periods=2).mean())
    )
    global_lookup = yearly_global.to_dict()
    final_global = (
        combined[combined.is_training]
        .groupby("calendar_month")
        .y.mean()
        .to_dict()
    )
    combined["global_prior"] = [
        global_lookup.get((year, month), final_global.get(month, np.nan))
        for year, month in zip(combined.year, combined.calendar_month)
    ]
    combined["seasonal_prior"] = (
        prior_sum + 5 * combined.global_prior
    ) / (prior_count + 5)

    for field in ("rain_sum", "soil_mean"):
        training_values = combined[field].where(combined.is_training)
        combined[f"{field}_normal"] = training_values.groupby(
            [combined.county_name, combined.calendar_month]
        ).transform(
            lambda values: values.shift(1).expanding(min_periods=2).mean()
        )
        combined[f"{field}_std"] = training_values.groupby(
            [combined.county_name, combined.calendar_month]
        ).transform(
            lambda values: values.shift(1).expanding(min_periods=2).std(ddof=0)
        )

    for field in BASE_MONTHLY_FIELDS:
        for window in (1, 3, 6):
            combined[f"{field}_{window}m"] = combined.groupby(
                "county_name"
            )[field].transform(
                lambda values, size=window: values.rolling(
                    size, min_periods=size
                ).mean()
            )

    grouped = combined.groupby("county_name")
    combined["rain_trend3"] = (
        combined.rain_sum - grouped.rain_sum.shift(2)
    ) / 2
    combined["soil_trend3"] = (
        combined.soil_mean - grouped.soil_mean.shift(2)
    ) / 2
    combined["rain_trend6"] = (
        combined.rain_sum - grouped.rain_sum.shift(5)
    ) / 5
    combined["soil_trend6"] = (
        combined.soil_mean - grouped.soil_mean.shift(5)
    ) / 5
    combined["rain_anomaly"] = (
        combined.rain_sum - combined.rain_sum_normal
    ) / (combined.rain_sum_std.fillna(0) + 1e-6)
    combined["soil_anomaly"] = (
        combined.soil_mean - combined.soil_mean_normal
    ) / (combined.soil_mean_std.fillna(0) + 1e-6)
    combined["ytd_rain_mean"] = combined.groupby(
        ["county_name", "year"]
    ).rain_sum.transform(lambda values: values.expanding().mean())
    combined["ytd_soil_mean"] = combined.groupby(
        ["county_name", "year"]
    ).soil_mean.transform(lambda values: values.expanding().mean())

    combined["target_rain_sum_lag12"] = _prior_year_feature(
        combined, "rain_sum", (12,)
    )
    combined["target_rain_sum_lag24mean"] = _prior_year_feature(
        combined, "rain_sum", (12, 24)
    )
    combined["target_soil_mean_lag12"] = _prior_year_feature(
        combined, "soil_mean", (12,)
    )
    combined["target_soil_mean_lag24mean"] = _prior_year_feature(
        combined, "soil_mean", (12, 24)
    )
    combined["target_high_days_lag12"] = _prior_year_feature(
        combined, "high_days", (12,)
    )
    combined["target_high_days_lag24mean"] = _prior_year_feature(
        combined, "high_days", (12, 24)
    )

    issue_columns = [
        "county_name",
        "month",
        "rain_sum",
        "soil_mean",
        "rain_sum_normal",
        "soil_mean_normal",
        "rain_anomaly",
        "soil_anomaly",
        "rain_trend3",
        "soil_trend3",
        "rain_trend6",
        "soil_trend6",
        "ytd_rain_mean",
        "ytd_soil_mean",
        *ROLLING_FEATURES,
    ]
    issue = combined[issue_columns].rename(
        columns={
            "month": "issue_month",
            "rain_sum": "issue_rain_sum",
            "soil_mean": "issue_soil_mean",
            "rain_sum_normal": "issue_rain_sum_normal",
            "soil_mean_normal": "issue_soil_mean_normal",
        }
    )
    target_columns = [
        "county_name",
        "month",
        "year",
        "calendar_month",
        "is_training",
        "y",
        "emdat_days",
        "seasonal_prior",
        "rain_sum_normal",
        "soil_mean_normal",
        "target_rain_sum_lag12",
        "target_rain_sum_lag24mean",
        "target_soil_mean_lag12",
        "target_soil_mean_lag24mean",
        "target_high_days_lag12",
        "target_high_days_lag24mean",
    ]
    samples = []
    for lead in LEADS:
        target = combined[target_columns].copy()
        target["issue_month"] = target.month - lead
        target["lead"] = lead
        samples.append(
            target.merge(issue, on=["county_name", "issue_month"], how="inner")
        )
    result = pd.concat(samples, ignore_index=True)
    result["target_month_sin"] = np.sin(
        2 * np.pi * result.calendar_month / 12
    )
    result["target_month_cos"] = np.cos(
        2 * np.pi * result.calendar_month / 12
    )
    return result.dropna(subset=MODEL_FEATURES).reset_index(drop=True)


def _forest():
    return RandomForestClassifier(
        n_estimators=400,
        max_depth=8,
        min_samples_leaf=4,
        max_features="sqrt",
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=-1,
    )


def _random_forest_scores(train, test):
    """Fit on all evidence available at issue time and return RF scores.

    Platt and isotonic post-hoc calibration were evaluated independently for
    each lead.  Both reduced chronological average precision and worsened the
    Brier score, while Platt calibration also collapsed county probabilities
    towards the overall event rate.  The Random Forest's own class
    probabilities are therefore the accepted evidence scores.
    """
    model = _forest()
    model.fit(train[list(MODEL_FEATURES)], train.y)
    scores = model.predict_proba(test[list(MODEL_FEATURES)])[:, 1]
    return scores, model


def _legacy_scores(train, test):
    fields = ["seasonal_prior", *ROLLING_FEATURES]
    adjusted = make_pipeline(
        StandardScaler(),
        LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            random_state=42,
            solver="liblinear",
        ),
    )
    adjusted.fit(train[fields], train.y)
    return (
        0.9 * test.seasonal_prior.to_numpy()
        + 0.1 * adjusted.predict_proba(test[fields])[:, 1]
    )


def _best_threshold(y_true, scores, *, beta=2):
    best = (float("-inf"), 0.5)
    for threshold in sorted(set(float(value) for value in scores)):
        predicted = scores >= threshold
        tp = int(((y_true == 1) & predicted).sum())
        fp = int(((y_true == 0) & predicted).sum())
        fn = int(((y_true == 1) & ~predicted).sum())
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        beta_squared = beta * beta
        denominator = beta_squared * precision + recall
        score = (
            (1 + beta_squared) * precision * recall / denominator
            if denominator
            else 0
        )
        candidate = (score, threshold)
        if candidate > best:
            best = candidate
    return best[1]


def _watch_threshold(y_true, scores, high_threshold, target_recall=0.8):
    candidates = []
    positives = int((y_true == 1).sum())
    for threshold in sorted(set(float(value) for value in scores)):
        if threshold >= high_threshold:
            continue
        caught = int(((y_true == 1) & (scores >= threshold)).sum())
        recall = caught / positives if positives else 0
        if recall >= target_recall:
            candidates.append(threshold)
    return max(candidates) if candidates else max(0.0, high_threshold * 0.5)


def _supported_high_threshold(y_true, scores, minimum_precision=0.5):
    """Return the highest-recall threshold that still earns a High label.

    A lead that never reaches 50% validation precision does not receive a High
    display band.  This prevents a weak long-lead model from manufacturing red
    counties simply to make the map look busy.
    """
    candidates = []
    positives = int((y_true == 1).sum())
    for threshold in sorted(set(float(value) for value in scores)):
        predicted = scores >= threshold
        tp = int(((y_true == 1) & predicted).sum())
        fp = int(((y_true == 0) & predicted).sum())
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / positives if positives else 0
        if precision >= minimum_precision:
            candidates.append((recall, precision, threshold))
    if not candidates:
        return float(np.nextafter(float(np.max(scores)), math.inf)), False
    _, _, threshold = max(candidates)
    return float(threshold), True


def _metrics(y_true, scores, *, threshold=None):
    if threshold is None:
        threshold = _best_threshold(y_true, scores, beta=1)
    predicted = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(
        y_true, predicted, labels=[0, 1]
    ).ravel()
    return {
        "average_precision": float(average_precision_score(y_true, scores)),
        "brier_score": float(brier_score_loss(y_true, scores)),
        "threshold": float(threshold),
        "high_risk_recall": float(tp / (tp + fn) if tp + fn else 0),
        "caught_high_risk_months": int(tp),
        "missed_high_risk_months": int(fn),
        "false_advisories": int(fp),
        "confusion_matrix": {
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        },
    }


def evaluate_samples(samples):
    """Replay 2023-2025 using an expanding, strictly chronological design."""
    folds = []
    for lead in LEADS:
        lead_rows = samples[
            samples.is_training & samples.lead.eq(lead)
        ].copy()
        for year in EVALUATION_YEARS:
            train = lead_rows[lead_rows.year < year]
            test = lead_rows[lead_rows.year.eq(year)]
            if train.y.nunique() != 2 or test.empty:
                continue
            forecast, _ = _random_forest_scores(train, test)
            legacy = _legacy_scores(train, test)
            fold = test[
                ["county_name", "month", "lead", "year", "y"]
            ].copy()
            fold["seasonal_score"] = test.seasonal_prior.to_numpy()
            fold["legacy_score"] = legacy
            fold["forecast_score"] = forecast
            folds.append(fold)
    if not folds:
        raise EvidenceOutlookError("No chronological evaluation folds were produced.")
    predictions = pd.concat(folds, ignore_index=True)
    report = []
    thresholds = {}
    for lead, rows in predictions.groupby("lead"):
        y_true = rows.y.to_numpy()
        forecast_scores = rows.forecast_score.to_numpy()
        # High requires at least 50% validation precision. Medium uses the
        # validation F1 optimum so planning coverage balances missed events
        # against false advisories instead of flagging almost every county.
        high, high_supported = _supported_high_threshold(
            y_true, forecast_scores
        )
        medium = _best_threshold(y_true, forecast_scores, beta=1)
        if medium >= high:
            medium = _watch_threshold(y_true, forecast_scores, high)
        thresholds[int(lead)] = {
            "high": float(high),
            "medium": float(medium),
            "high_supported": high_supported,
        }
        report.append(
            {
                "lead": int(lead),
                "test_years": list(EVALUATION_YEARS),
                "seasonal_baseline": _metrics(
                    y_true, rows.seasonal_score.to_numpy()
                ),
                "legacy_90_10": _metrics(y_true, rows.legacy_score.to_numpy()),
                "evidence_random_forest": _metrics(
                    y_true,
                    forecast_scores,
                    threshold=medium,
                ),
                "display_high_performance": (
                    _metrics(
                        y_true,
                        forecast_scores,
                        threshold=high,
                    )
                    if high_supported
                    else None
                ),
                "display_thresholds": thresholds[int(lead)],
            }
        )
    accepted = all(
        row["evidence_random_forest"]["average_precision"]
        >= row["legacy_90_10"]["average_precision"] + 0.01
        and row["evidence_random_forest"]["brier_score"]
        <= row["legacy_90_10"]["brier_score"] + 0.005
        for row in report
    )
    return {
        "accepted": accepted,
        "leads": report,
        "probability_method": (
            "Random Forest class probabilities. Lead-specific Platt and "
            "isotonic post-hoc calibration were rejected because they "
            "reduced chronological average precision and worsened Brier "
            "score; Platt calibration also collapsed county separation."
        ),
        "acceptance_rule": (
            "Every lead must improve average precision by at least 0.01 over "
            "the 90/10 model without worsening Brier score by more than 0.005."
        ),
    }, thresholds, predictions


def evaluate_target_candidates(historical_monthly):
    candidates = {}
    accepted_target = None
    for target_days in TARGET_DAY_CANDIDATES:
        samples = build_samples(
            historical_monthly, target_days=target_days
        )
        report, thresholds, _ = evaluate_samples(samples)
        report["positive_rate"] = float(
            historical_monthly.high_days.ge(target_days).mean()
        )
        candidates[str(target_days)] = report
        if report["accepted"] and target_days == ACCEPTED_TARGET_DAYS:
            accepted_target = target_days
    if accepted_target is None:
        raise EvidenceOutlookError(
            "The seven-day monthly target did not pass the acceptance rule. "
            "The existing release was kept."
        )
    return accepted_target, candidates


def fit_release(samples, *, cutoff_month, thresholds):
    publication = {}
    details = {}
    for lead in LEADS:
        target_month = cutoff_month + lead
        current = samples[
            ~samples.is_training
            & samples.lead.eq(lead)
            & samples.month.eq(target_month)
        ].copy()
        training = samples[samples.is_training & samples.lead.eq(lead)]
        expected_counties = set(samples[~samples.is_training].county_name)
        if set(current.county_name) != expected_counties:
            raise EvidenceOutlookError(
                f"Lead {lead} does not cover every current county."
            )
        scores, _ = _random_forest_scores(training, current)
        month_key = str(target_month)
        publication[month_key] = {}
        details[month_key] = {}
        bands = thresholds[lead]
        for row, score in zip(current.itertuples(index=False), scores):
            band = (
                "High"
                if bands["high_supported"] and score >= bands["high"]
                else "Medium"
                if score >= bands["medium"]
                else "Low"
            )
            rainfall = float(row.issue_rain_sum)
            rainfall_normal = float(row.issue_rain_sum_normal)
            soil = float(row.issue_soil_mean)
            soil_normal = float(row.issue_soil_mean_normal)
            rain_difference = (
                100 * (rainfall - rainfall_normal) / rainfall_normal
                if rainfall_normal
                else 0
            )
            evidence = (
                f"Recent monthly rainfall was {abs(rain_difference):.0f}% "
                f"{'above' if rain_difference >= 0 else 'below'} the county normal; "
                f"soil wetness was {soil:.2f} versus {soil_normal:.2f} normally; "
                f"historical seasonal susceptibility was "
                f"{float(row.seasonal_prior) * 100:.1f}%."
            )
            publication[month_key][row.county_name] = float(score)
            details[month_key][row.county_name] = {
                "band": band,
                "score": float(score),
                "lead_months": int(lead),
                "high_threshold": float(bands["high"]),
                "medium_threshold": float(bands["medium"]),
                "high_band_supported": bool(bands["high_supported"]),
                "recent_rainfall_mm": rainfall,
                "normal_rainfall_mm": rainfall_normal,
                "rainfall_difference_pct": float(rain_difference),
                "recent_soil_wetness": soil,
                "normal_soil_wetness": soil_normal,
                "historical_susceptibility": float(row.seasonal_prior),
                "recent_high_risk_days": float(row.high_days_1m),
                "comparison_month": str(row.issue_month),
                "why": evidence,
            }
    validate_release_sanity(publication, details)
    return publication, details


def validate_release_sanity(publication, details):
    """Refuse a release that has lost useful county differentiation.

    This guard never changes a county's score or band.  It preserves the last
    accepted release when a modelling or calibration failure collapses an
    entire target month into one indistinguishable display class.
    """
    for month, county_scores in publication.items():
        scores = np.asarray(list(county_scores.values()), dtype=float)
        bands = {
            entry["band"] for entry in details.get(month, {}).values()
        }
        if len(scores) < 2 or not np.isfinite(scores).all():
            raise EvidenceOutlookError(
                f"{month} contains incomplete or invalid outlook scores."
            )
        if float(np.ptp(scores)) < 0.02:
            raise EvidenceOutlookError(
                f"{month} scores collapsed to a range below 0.02. "
                "The existing release was kept."
            )
        if len(bands) < 2:
            raise EvidenceOutlookError(
                f"{month} assigned every county to {next(iter(bands))}. "
                "The existing release was kept."
            )


def build_label_audit(monthly, daily_history):
    audit = {
        "period": {
            "first": str(monthly.month.min()),
            "last": str(monthly.month.max()),
            "county_months": int(len(monthly)),
        },
        "target_sensitivity": {},
    }
    emdat = monthly.emdat_days.gt(0)
    for target_days in TARGET_DAY_CANDIDATES:
        target = monthly.high_days.ge(target_days)
        audit["target_sensitivity"][str(target_days)] = {
            "positive_county_months": int(target.sum()),
            "positive_rate": float(target.mean()),
            "emdat_and_target": int((emdat & target).sum()),
            "emdat_without_target": int((emdat & ~target).sum()),
            "target_without_emdat": int((~emdat & target).sum()),
        }
    mapped = (
        daily_history[daily_history.emdat_day.eq(1)]
        .groupby("alignment_date")
        .county_name.nunique()
        .sort_values(ascending=False)
    )
    audit["broad_event_mapping"] = {
        "dates_affecting_ten_or_more_counties": int(mapped.ge(10).sum()),
        "maximum_counties_on_one_date": int(mapped.max()) if len(mapped) else 0,
        "largest_dates": [
            {"date": date.isoformat(), "counties": int(count)}
            for date, count in mapped.head(12).items()
        ],
    }
    reviewed = (*ARID_REVIEW_COUNTIES, *COMPARISON_COUNTIES)
    county_summary = (
        monthly[monthly.county_name.isin(reviewed)]
        .assign(target_7=lambda frame: frame.high_days.ge(7))
        .groupby("county_name")
        .agg(
            mean_monthly_rainfall_mm=("rain_sum", "mean"),
            mean_soil_wetness=("soil_mean", "mean"),
            emdat_months=("emdat_days", lambda values: int(values.gt(0).sum())),
            seven_day_target_months=("target_7", "sum"),
        )
    )
    audit["county_review"] = {
        name: {
            key: (int(value) if key.endswith("months") else float(value))
            for key, value in row.items()
        }
        for name, row in county_summary.to_dict(orient="index").items()
    }
    return audit


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, allow_nan=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)
