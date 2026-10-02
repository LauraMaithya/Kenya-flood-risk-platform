from rest_framework import serializers

from monitoring.models import (
    AlertNotification,
    County,
    EnvironmentalObservation,
    FloodPrediction,
)


class CountySerializer(serializers.ModelSerializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()

    class Meta:
        model = County
        fields = (
            "id",
            "code",
            "name",
            "slug",
            "latitude",
            "longitude",
            "has_nasa_power_coverage",
        )


class EnvironmentalObservationSerializer(
    serializers.ModelSerializer
):
    county_code = serializers.CharField(
        source="county.code",
        read_only=True,
    )
    county_name = serializers.CharField(
        source="county.name",
        read_only=True,
    )
    precipitation_max_mm = serializers.FloatField()
    temperature_mean_c = serializers.FloatField()
    relative_humidity_mean_pct = serializers.FloatField()
    soil_wetness_mean_fraction = serializers.FloatField()
    soil_wetness_max_fraction = serializers.FloatField()
    month_sin = serializers.FloatField()
    month_cos = serializers.FloatField()

    class Meta:
        model = EnvironmentalObservation
        fields = (
            "id",
            "county_code",
            "county_name",
            "observation_date",
            "precipitation_max_mm",
            "temperature_mean_c",
            "relative_humidity_mean_pct",
            "soil_wetness_mean_fraction",
            "soil_wetness_max_fraction",
            "month_sin",
            "month_cos",
            "source",
            "quality_review_required",
            "ingested_at",
        )


class FloodPredictionSerializer(serializers.ModelSerializer):
    observation_id = serializers.IntegerField(read_only=True)
    county_code = serializers.CharField(
        source="observation.county.code",
        read_only=True,
    )
    county_name = serializers.CharField(
        source="observation.county.name",
        read_only=True,
    )
    observation_date = serializers.DateField(
        source="observation.observation_date",
        read_only=True,
    )
    probability_low = serializers.FloatField()
    probability_medium = serializers.FloatField()
    probability_high = serializers.FloatField()
    high_probability_threshold = serializers.FloatField()

    class Meta:
        model = FloodPrediction
        fields = (
            "id",
            "observation_id",
            "county_code",
            "county_name",
            "observation_date",
            "risk_level",
            "probability_low",
            "probability_medium",
            "probability_high",
            "model_release_id",
            "decision_rule",
            "high_probability_threshold",
            "predicted_at",
        )


class AlertNotificationSerializer(serializers.ModelSerializer):
    prediction_id = serializers.IntegerField(read_only=True)
    county_code = serializers.CharField(
        source="prediction.observation.county.code",
        read_only=True,
    )
    county_name = serializers.CharField(
        source="prediction.observation.county.name",
        read_only=True,
    )
    observation_date = serializers.DateField(
        source="prediction.observation.observation_date",
        read_only=True,
    )
    risk_level = serializers.CharField(
        source="prediction.risk_level",
        read_only=True,
    )
    probability_high = serializers.FloatField(
        source="prediction.probability_high",
        read_only=True,
    )

    class Meta:
        model = AlertNotification
        fields = (
            "id",
            "prediction_id",
            "county_code",
            "county_name",
            "observation_date",
            "risk_level",
            "probability_high",
            "channel",
            "message",
            "status",
            "created_at",
            "sent_at",
        )