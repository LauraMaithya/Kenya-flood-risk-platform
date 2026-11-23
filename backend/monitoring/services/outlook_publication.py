"""Validate and atomically publish a complete three-month outlook."""

import json
import math
import os
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile


def publish_outlook(
    path,
    *,
    issued_on,
    observed_through,
    scores,
    county_names,
    model_details=None,
    thresholds=None,
    details=None,
):
    if not isinstance(issued_on, date) or not isinstance(observed_through, date):
        raise ValueError("Issue date and observation cutoff are required.")
    issue_month = issued_on.year * 12 + issued_on.month - 1
    expected = set()
    for offset in (1, 2, 3):
        year, month = divmod(issue_month + offset, 12)
        expected.add(f"{year:04d}-{month + 1:02d}")
    if set(scores) != expected or observed_through >= issued_on:
        raise ValueError("Expected the next three calendar months and a prior observation cutoff.")
    counties = set(county_names)
    if not counties:
        raise ValueError("Expected at least one covered county.")
    for estimates in scores.values():
        if set(estimates) != counties or any(
            type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1
            for score in estimates.values()
        ):
            raise ValueError("Every target month requires a valid score for every covered county.")
    payload = {
        "issued_on": issued_on.isoformat(),
        "observed_through": observed_through.isoformat(),
        "scores": scores,
    }
    if model_details is not None:
        if not isinstance(model_details, dict):
            raise ValueError("Model details must be a dictionary.")
        payload["model"] = model_details
    if thresholds is not None:
        if not isinstance(thresholds, dict):
            raise ValueError("Thresholds must be a dictionary.")
        payload["thresholds"] = thresholds
    if details is not None:
        if set(details) != expected:
            raise ValueError("Evidence details must cover all target months.")
        for month_details in details.values():
            if set(month_details) != counties:
                raise ValueError("Evidence details must cover every county.")
        payload["details"] = details
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, allow_nan=False, sort_keys=True)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
