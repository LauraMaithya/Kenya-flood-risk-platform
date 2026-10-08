from django.db.models import (
    Count,
    Max,
    Min,
    Q,
)

from monitoring.models import FloodPrediction


def historical_prediction_queryset(filters=None):
    filters = filters or {}

    queryset = (
        FloodPrediction.objects.filter(
            observation__is_synthetic=False
        )
        .select_related(
            "observation",
            "observation__county",
        )
        .order_by(
            "-observation__observation_date",
            "observation__county__name",
            "-predicted_at",
            "-pk",
        )
    )

    county = filters.get("county")
    risk_level = filters.get("risk_level")
    year = filters.get("year")
    start_date = filters.get("start_date")
    end_date = filters.get("end_date")

    if county:
        queryset = queryset.filter(
            observation__county=county
        )

    if risk_level:
        queryset = queryset.filter(
            risk_level=risk_level
        )

    if year:
        queryset = queryset.filter(
            observation__observation_date__year=year
        )

    if start_date:
        queryset = queryset.filter(
            observation__observation_date__gte=(
                start_date
            )
        )

    if end_date:
        queryset = queryset.filter(
            observation__observation_date__lte=(
                end_date
            )
        )

    return queryset


def historical_coverage_summary(queryset):
    summary = queryset.aggregate(
        total_records=Count("pk"),
        counties_covered=Count(
            "observation__county_id",
            distinct=True,
        ),
        first_date=Min(
            "observation__observation_date"
        ),
        last_date=Max(
            "observation__observation_date"
        ),
        high_count=Count(
            "pk",
            filter=Q(
                risk_level=(
                    FloodPrediction.RiskLevel.HIGH
                )
            ),
        ),
        medium_count=Count(
            "pk",
            filter=Q(
                risk_level=(
                    FloodPrediction.RiskLevel.MEDIUM
                )
            ),
        ),
        low_count=Count(
            "pk",
            filter=Q(
                risk_level=(
                    FloodPrediction.RiskLevel.LOW
                )
            ),
        ),
    )

    total = summary["total_records"]

    for risk_name in (
        "high",
        "medium",
        "low",
    ):
        count = summary[f"{risk_name}_count"]

        summary[f"{risk_name}_percentage"] = (
            round((count / total) * 100, 1)
            if total
            else 0.0
        )

    return summary