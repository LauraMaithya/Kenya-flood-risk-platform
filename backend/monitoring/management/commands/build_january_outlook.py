import json
from pathlib import Path

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import localdate
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from monitoring.services.monthly_outlook import EVENT_YEARS, JANUARY_RELEASE, seasonal_outlook
from monitoring.models import EnvironmentalObservation
from monitoring.services.outlook_publication import publish_outlook


class Command(BaseCommand):
    help = "Build the January 2027 lead-three outlook using May–October 2026 weather."

    def add_arguments(self, parser):
        parser.add_argument("--history", required=True, type=Path)
        parser.add_argument("--weather", required=True, type=Path)
        parser.add_argument("--rolling", action="store_true", help="Publish the next three calendar months.")

    def handle(self, *args, **options):
        fields = ["precipitation_max_mm", "soil_wetness_mean_fraction"]
        history = pd.read_csv(options["history"], parse_dates=["alignment_date"])
        weather = pd.read_csv(options["weather"], parse_dates=["observation_date"])
        expected = pd.date_range("2026-05-01", "2026-10-31")
        if (set(weather.county_name) != set(EVENT_YEARS)
                or len(weather) != len(EVENT_YEARS) * len(expected)
                or weather.duplicated(["county_name", "observation_date"]).any()
                or set(weather.observation_date) != set(expected)
                or not np.isfinite(weather[fields]).all().all()):
            raise CommandError("Weather must contain all 184 days for each covered county.")
        if (len(history) != 198696 or set(history.county_name) != set(EVENT_YEARS)
                or history.is_synthetic.any()
                or history.duplicated(["county_name", "alignment_date"]).any()
                or not np.isfinite(history[fields]).all().all()):
            raise CommandError("Use the original real_model_features.csv export.")

        def monthly(frame, date_field):
            frame = frame.copy()
            frame["month"] = frame[date_field].dt.to_period("M")
            frame["recorded"] = frame.get("label_evidence_basis", pd.Series(index=frame.index, dtype=str)).eq(
                "DOCUMENTED_EMDAT_FLOOD_EVENT"
            )
            return frame.groupby(["county_name", "month"]).agg(
                rain=(fields[0], "max"), soil=(fields[1], "mean"), y=("recorded", "max")
            ).reset_index()

        train = monthly(history, "alignment_date")
        if options["rolling"]:
            today = localdate()
            issue_month = pd.Period(today, freq="M")
            earliest = (issue_month - 8).start_time.date()
            observations = EnvironmentalObservation.objects.filter(
                source=EnvironmentalObservation.Source.NASA_POWER,
                is_synthetic=False,
                county__name__in=EVENT_YEARS,
                observation_date__gte=earliest,
                observation_date__lt=issue_month.start_time.date(),
            ).values_list("county__name", "observation_date", *fields)
            observed = pd.DataFrame.from_records(observations, columns=["county_name", "observation_date", *fields])
            observed["observation_date"] = pd.to_datetime(observed.observation_date)
            observed[fields] = observed[fields].astype(float)
            if observed.duplicated(["county_name", "observation_date"]).any():
                raise CommandError("Duplicate database weather observations.")
            weather = pd.concat([weather, observed.dropna(subset=fields)], ignore_index=True)
            weather = weather.drop_duplicates(["county_name", "observation_date"], keep="first")
            for age in (1, 2, 3):
                cutoff = issue_month - age
                dates = pd.date_range((cutoff - 5).start_time, cutoff.end_time.normalize())
                snapshot = weather[weather.observation_date.isin(dates)]
                if len(snapshot) == len(EVENT_YEARS) * len(dates):
                    break
            else:
                raise CommandError("No complete recent six-month window. Previous release kept.")
            recent = monthly(snapshot, "observation_date")
            publication = {}
            for offset in (1, 2, 3):
                target = issue_month + offset
                publication[str(target)] = self.fit_scores(
                    train.copy(), recent, target.ordinal - cutoff.ordinal, target.month
                )
            publish_outlook(
                JANUARY_RELEASE.with_name("outlook-current.json"),
                issued_on=today, observed_through=cutoff.end_time.date(),
                scores=publication, county_names=EVENT_YEARS,
            )
            self.stdout.write(self.style.SUCCESS(
                f"Published {', '.join(publication)} using observations through {cutoff}."
            ))
            return
        recent = monthly(weather, "observation_date")
        scores = self.fit_scores(train, recent, 3, 1)
        JANUARY_RELEASE.parent.mkdir(parents=True, exist_ok=True)
        temporary = JANUARY_RELEASE.with_suffix(".tmp")
        temporary.write_text(json.dumps(scores, indent=2), encoding="utf-8")
        temporary.replace(JANUARY_RELEASE)
        self.stdout.write(self.style.SUCCESS(f"Saved January estimates for {len(scores)} counties."))

    def fit_scores(self, train, recent, lead, month):
        features = []
        for field in ("rain", "soil"):
            for window in (1, 3, 6):
                key = f"{field}_{window}"
                features.append(key)
                train[key] = train.groupby("county_name")[field].transform(
                    lambda values: values.shift(lead).rolling(window).mean()
                )
        train = train.dropna(subset=features).copy()
        train["season"] = train.month.dt.month
        group = train.groupby(["county_name", "season"]).y
        pool = train.groupby("season").y
        own = train.y.astype(int)
        p = ((group.transform("sum") - own
              + 5 * (pool.transform("sum") - own) / (pool.transform("size") - 1))
             / (group.transform("size") + 4))

        def logit(values):
            clipped = np.clip(values, .0001, .9999)
            return np.log(clipped / (1 - clipped))

        model = make_pipeline(StandardScaler(), LogisticRegression())
        model.fit(np.column_stack([train[features], logit(p)]), train.y)
        scores = {}
        for name, rows in recent.groupby("county_name"):
            values = [rows[field].tail(window).mean()
                      for field in ("rain", "soil") for window in (1, 3, 6)]
            baseline = seasonal_outlook(name, month)
            adjusted = model.predict_proba([[*values, logit(baseline)]])[0, 1]
            scores[name] = float(.9 * baseline + .1 * adjusted)
        return scores
