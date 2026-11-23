"""County seasonal baseline from real_model_features.csv (2010–2025).

Each entry counts years with at least one DOCUMENTED_EMDAT_FLOOD_EVENT
day for that county and calendar month. These are reporting proxies.
"""

import re
import json
from datetime import date
from pathlib import Path

JANUARY_RELEASE = Path(__file__).resolve().parents[3] / "logs" / "outlook-2027-01.json"


def _load_current_payload():
    return json.loads(
        JANUARY_RELEASE.with_name("outlook-current.json").read_text(
            encoding="utf-8"
        )
    )


def available_outlook_months():
    """Return target months from the last successfully published release."""
    try:
        scores = _load_current_payload().get("scores", {})
    except (OSError, ValueError, TypeError, AttributeError):
        return ()
    if not isinstance(scores, dict):
        return ()
    available = []
    for value in scores:
        try:
            year, month = (int(part) for part in value.split("-", 1))
            date(year, month, 1)
        except (AttributeError, TypeError, ValueError):
            continue
        available.append(f"{year:04d}-{month:02d}")
    return tuple(sorted(set(available)))


def load_rolling_outlook(year, month):
    if year is None or month is None:
        return {}, None
    try:
        payload = _load_current_payload()
        scores = payload["scores"].get(f"{year:04d}-{month:02d}", {})
        issued = date.fromisoformat(payload["issued_on"])
        cutoff = date.fromisoformat(payload["observed_through"])
        lead = (year - cutoff.year) * 12 + month - cutoff.month
        model = payload.get("model", {})
        model_name = model.get("name")
        if model_name:
            inputs = model.get("inputs", [])
            input_summary = ", ".join(inputs[:2]) if inputs else "validated evidence"
            basis = (
                f"Issued {issued} · observations through {cutoff} · "
                f"{lead}-month lead from data cutoff · {model_name} using "
                f"{input_summary}"
            )
        else:
            basis = (
                f"Issued {issued} · real NASA POWER observations through {cutoff} "
                f"· {lead}-month lead from data cutoff "
                "· 90% seasonal baseline + 10% weather-adjusted estimate"
            )
        return scores, basis
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}, None


def load_rolling_outlook_details(year, month):
    """Return per-county evidence and calibrated bands for one release month."""
    if year is None or month is None:
        return {}
    try:
        payload = _load_current_payload()
        details = payload.get("details", {}).get(
            f"{year:04d}-{month:02d}", {}
        )
        return details if isinstance(details, dict) else {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def load_outlook_release(year, month):
    if (year, month) != (2027, 1):
        return {}
    try:
        payload = json.loads(JANUARY_RELEASE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {name: score for name, score in payload.items()
            if type(score) in (float, int) and 0 <= score <= 1}

HISTORICAL_YEARS = 16
EVENT_YEARS = {
    'Baringo': (1, 0, 2, 3, 2, 0, 0, 1, 0, 0, 1, 1),
    'Busia': (1, 0, 2, 3, 4, 0, 0, 0, 0, 0, 1, 2),
    'Elgeyo-Marakwet': (1, 0, 2, 4, 3, 1, 0, 0, 0, 1, 2, 2),
    'Embu': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    'Garissa': (0, 0, 3, 4, 5, 1, 0, 0, 0, 1, 2, 1),
    'Homa Bay': (0, 0, 1, 4, 4, 1, 0, 0, 0, 1, 2, 2),
    'Isiolo': (1, 0, 3, 2, 2, 0, 0, 0, 0, 1, 2, 3),
    'Kajiado': (0, 0, 2, 2, 2, 0, 0, 0, 0, 1, 1, 2),
    'Kiambu': (0, 0, 2, 3, 3, 0, 0, 0, 0, 0, 0, 0),
    'Kilifi': (0, 0, 2, 4, 4, 1, 0, 0, 0, 1, 1, 1),
    'Kitui': (0, 0, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1),
    'Kwale': (0, 0, 2, 1, 1, 0, 0, 0, 0, 1, 1, 1),
    'Laikipia': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1),
    'Lamu': (0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0),
    'Machakos': (1, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 2),
    'Makueni': (0, 0, 1, 1, 1, 0, 0, 0, 0, 1, 1, 2),
    'Mandera': (1, 0, 3, 3, 3, 0, 0, 0, 0, 1, 1, 2),
    'Marsabit': (1, 0, 3, 4, 4, 0, 0, 0, 0, 1, 2, 3),
    'Meru': (0, 0, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1),
    'Migori': (0, 0, 1, 2, 2, 0, 0, 0, 0, 0, 0, 0),
    'Nakuru': (0, 0, 2, 4, 4, 0, 0, 0, 0, 0, 0, 0),
    'Nandi': (2, 0, 1, 1, 1, 0, 0, 0, 0, 1, 1, 2),
    'Narok': (1, 0, 2, 3, 3, 0, 0, 0, 0, 1, 1, 3),
    'Nyamira': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    'Nyeri': (0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0),
    'Samburu': (0, 0, 2, 2, 2, 0, 0, 0, 0, 1, 2, 2),
    'Siaya': (0, 0, 1, 2, 2, 1, 0, 0, 0, 1, 2, 2),
    'Taita Taveta': (0, 0, 2, 2, 2, 0, 0, 0, 0, 1, 1, 2),
    'Tana River': (1, 0, 5, 7, 7, 1, 0, 0, 0, 1, 2, 3),
    'Tharaka': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    'Trans Nzoia': (2, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 2),
    'Turkana': (1, 0, 6, 5, 4, 0, 0, 1, 1, 1, 1, 1),
    'Wajir': (1, 0, 2, 2, 3, 0, 0, 0, 0, 1, 2, 3),
    'West Pokot': (1, 0, 3, 3, 2, 1, 0, 0, 0, 1, 2, 2),
}


def _county_key(name):
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return "tharaka" if key == "tharakanithi" else key


_BY_KEY = {_county_key(name): counts for name, counts in EVENT_YEARS.items()}


def seasonal_outlook(county_name, month):
    counts = _BY_KEY.get(_county_key(county_name))
    if counts is None:
        return None
    index = month - 1
    seasonal_mean = sum(v[index] for v in EVENT_YEARS.values()) / (
        len(EVENT_YEARS) * HISTORICAL_YEARS
    )
    return (counts[index] + 5 * seasonal_mean) / (HISTORICAL_YEARS + 5)
