from monitoring.models import FloodPrediction


def county_prediction_queryset(county):
    return (
        FloodPrediction.objects.select_related(
            "observation",
            "observation__county",
        )
        .filter(
            observation__county=county,
            observation__is_synthetic=False,
        )
        .order_by(
            "-observation__observation_date",
            "-predicted_at",
            "-pk",
        )
    )
def latest_county_prediction(county):
    return county_prediction_queryset(county).first()
def recent_county_predictions(county, limit=10):
    return county_prediction_queryset(county)[:limit]