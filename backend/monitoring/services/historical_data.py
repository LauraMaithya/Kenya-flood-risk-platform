from monitoring.models import FloodPrediction


def historical_prediction_queryset(filters):
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

    if start_date:
        queryset = queryset.filter(
            observation__observation_date__gte=start_date
        )

    if end_date:
        queryset = queryset.filter(
            observation__observation_date__lte=end_date
        )

    return queryset