from django.contrib import admin

from .models import (
    AlertNotification,
    County,
    EnvironmentalObservation,
    FloodPrediction,
)


@admin.register(County)
class CountyAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "has_nasa_power_coverage",
        "updated_at",
    )
    list_filter = ("has_nasa_power_coverage",)
    search_fields = ("code", "name")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("name",)


@admin.register(EnvironmentalObservation)
class EnvironmentalObservationAdmin(admin.ModelAdmin):
    list_display = (
        "county",
        "observation_date",
        "source",
        "is_synthetic",
        "quality_review_required",
        "ingested_at",
    )
    list_filter = (
        "source",
        "is_synthetic",
        "quality_review_required",
    )
    search_fields = (
        "county__name",
        "county__code",
        "source_record_id",
    )
    date_hierarchy = "observation_date"
    list_select_related = ("county",)


@admin.register(FloodPrediction)
class FloodPredictionAdmin(admin.ModelAdmin):
    list_display = (
        "observation",
        "risk_level",
        "probability_high",
        "model_release_id",
        "predicted_at",
    )
    list_filter = (
        "risk_level",
        "model_release_id",
        "decision_rule",
    )
    search_fields = (
        "observation__county__name",
        "observation__county__code",
        "model_release_id",
    )
    list_select_related = (
        "observation",
        "observation__county",
    )


@admin.register(AlertNotification)
class AlertNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "prediction",
        "channel",
        "recipient",
        "status",
        "created_at",
        "sent_at",
    )
    list_filter = ("channel", "status")
    search_fields = (
        "recipient",
        "prediction__observation__county__name",
    )
    list_select_related = (
        "prediction",
        "prediction__observation",
        "prediction__observation__county",
    )