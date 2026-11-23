from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db.models import OuterRef, Subquery
from django.utils.timezone import localdate

from monitoring.models import EnvironmentalObservation, FloodPrediction
from monitoring.services.evidence_outlook import (
    ACCEPTED_TARGET_DAYS,
    EvidenceOutlookError,
    aggregate_history,
    aggregate_recent,
    build_label_audit,
    build_samples,
    evaluate_target_candidates,
    fit_release,
    latest_complete_month,
    write_json,
)
from monitoring.services.monthly_outlook import EVENT_YEARS, JANUARY_RELEASE
from monitoring.services.outlook_publication import publish_outlook


class Command(BaseCommand):
    help = (
        "Evaluate and publish the next three county flood outlook months using "
        "real history and the latest complete observations."
    )

    def add_arguments(self, parser):
        parser.add_argument("--history", required=True, type=Path)
        parser.add_argument(
            "--report",
            type=Path,
            default=Path("logs/monthly-outlook-evaluation.json"),
        )
        parser.add_argument(
            "--audit",
            type=Path,
            default=Path("logs/monthly-label-audit.json"),
        )
        # Retained so yesterday's scheduled task remains compatible. The
        # database now supplies the authoritative latest observations.
        parser.add_argument("--weather", type=Path)
        parser.add_argument("--forecast-cache", type=Path)
        parser.add_argument("--skip-download", action="store_true")

    def handle(self, *args, **options):
        try:
            history = pd.read_csv(options["history"])
            historical_monthly, daily_history = aggregate_history(history)
            if set(historical_monthly.county_name) != set(EVENT_YEARS):
                raise EvidenceOutlookError(
                    "Historical data must cover the same 34 outlook counties."
                )

            target_days, candidates = evaluate_target_candidates(
                historical_monthly
            )
            if target_days != ACCEPTED_TARGET_DAYS:
                raise EvidenceOutlookError(
                    "Only the validated seven-day target may be published."
                )
            selected_report = candidates[str(target_days)]
            thresholds = {
                row["lead"]: row["display_thresholds"]
                for row in selected_report["leads"]
            }

            recent = self._recent_observations(
                first_year=int(historical_monthly.month.dt.year.max()) + 1
            )
            recent_monthly = aggregate_recent(recent)
            cutoff = latest_complete_month(recent_monthly, EVENT_YEARS)
            issue_month = pd.Period(localdate(), freq="M")
            if cutoff != issue_month - 1:
                raise EvidenceOutlookError(
                    f"Latest complete month is {cutoff}; expected {issue_month - 1}. "
                    "The existing release was kept."
                )
            recent_monthly = recent_monthly[
                recent_monthly.month.le(cutoff)
            ].copy()
            samples = build_samples(
                historical_monthly,
                target_days=target_days,
                recent_monthly=recent_monthly,
            )
            scores, details = fit_release(
                samples,
                cutoff_month=cutoff,
                thresholds=thresholds,
            )

            audit = build_label_audit(historical_monthly, daily_history)
            audit.update(
                {
                    "selected_target_days": target_days,
                    "selection_reason": (
                        "Seven days was the only tested target that passed the "
                        "chronological acceptance rule at Leads 2, 3 and 4."
                    ),
                    "candidate_evaluations": candidates,
                }
            )
            report = {
                **selected_report,
                "evaluated_on": localdate().isoformat(),
                "selected_target": (
                    "At least seven daily High-risk classifications in the "
                    "target county-month"
                ),
                "training_period": "2010-01 through 2025-12",
                "test_design": (
                    "Expanding chronological replay for 2023-2025; every "
                    "fold trains only on years before its test year"
                ),
                "probability_method": selected_report["probability_method"],
                "observation_cutoff": cutoff.end_time.date().isoformat(),
                "daily_model_changed": False,
                "copernicus_dependency": False,
            }
            write_json(options["audit"], audit)
            write_json(options["report"], report)

            publish_outlook(
                JANUARY_RELEASE.with_name("outlook-current.json"),
                issued_on=localdate(),
                observed_through=cutoff.end_time.date(),
                scores=scores,
                county_names=EVENT_YEARS,
                model_details={
                    "name": "Lead-specific monthly Random Forest outlook",
                    "target": report["selected_target"],
                    "inputs": [
                        "real 2010-2025 county-day history",
                        "latest complete real rainfall and soil wetness",
                        "one-, three- and six-month lags",
                        "county-relative anomalies and trends",
                        "year-to-date conditions",
                        "historical susceptibility as one feature",
                    ],
                    "evaluation": report["test_design"],
                    "probability_method": report["probability_method"],
                    "threshold_selection": (
                        "Medium maximises validation F1 at each lead; High "
                        "requires at least 50% chronological precision."
                    ),
                    "accepted": True,
                    "daily_model_changed": False,
                },
                thresholds={str(key): value for key, value in thresholds.items()},
                details=details,
            )
        except (EvidenceOutlookError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        self._print_report(report)
        self.stdout.write(
            self.style.SUCCESS(
                "Published the next three months with evidence-based "
                "lead-specific classifications."
            )
        )
        self.stdout.write(
            "Future outlooks remain planning information. No warning emails "
            "were created."
        )

    def _recent_observations(self, *, first_year):
        latest_risk = FloodPrediction.objects.filter(
            observation_id=OuterRef("pk")
        ).order_by("-predicted_at", "-pk").values("risk_level")[:1]
        rows = list(
            EnvironmentalObservation.objects.filter(
                is_synthetic=False,
                observation_date__year__gte=first_year,
                observation_date__lt=localdate().replace(day=1),
                county__name__in=EVENT_YEARS,
            )
            .annotate(latest_risk_level=Subquery(latest_risk))
            .values(
                "county__name",
                "observation_date",
                "precipitation_max_mm",
                "soil_wetness_mean_fraction",
                "soil_wetness_max_fraction",
                "latest_risk_level",
            )
        )
        frame = pd.DataFrame.from_records(rows)
        if frame.empty:
            raise EvidenceOutlookError("No recent real observations were found.")
        frame = frame.rename(
            columns={
                "county__name": "county_name",
                "latest_risk_level": "risk_level",
            }
        )
        if frame.risk_level.isna().any():
            missing = int(frame.risk_level.isna().sum())
            raise EvidenceOutlookError(
                f"{missing} recent observations have no daily prediction. "
                "Run the existing prediction pipeline before publishing."
            )
        numeric = [
            "precipitation_max_mm",
            "soil_wetness_mean_fraction",
            "soil_wetness_max_fraction",
        ]
        frame[numeric] = frame[numeric].astype(float)
        return frame

    def _print_report(self, report):
        self.stdout.write("\nChronological monthly outlook evaluation")
        for row in report["leads"]:
            old = row["legacy_90_10"]
            new = row["evidence_random_forest"]
            display = row["display_thresholds"]
            high_performance = row["display_high_performance"]
            high_note = (
                f"High threshold {display['high']:.3f}, caught "
                f"{high_performance['caught_high_risk_months']}, missed "
                f"{high_performance['missed_high_risk_months']}, false "
                f"advisories {high_performance['false_advisories']}"
                if display["high_supported"]
                else "High band withheld at this lead"
            )
            self.stdout.write(
                f"Lead {row['lead']}: AP {old['average_precision']:.3f} -> "
                f"{new['average_precision']:.3f}; Brier "
                f"{old['brier_score']:.3f} -> {new['brier_score']:.3f}; "
                f"Medium watch caught {new['caught_high_risk_months']}, missed "
                f"{new['missed_high_risk_months']}, false advisories "
                f"{new['false_advisories']}; {high_note}."
            )
