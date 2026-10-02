from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class County(models.Model):
    code = models.CharField(
        max_length=3,
        unique=True,
        help_text="Official three-digit Kenya county code.",
    )
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    has_nasa_power_coverage = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "counties"
        indexes = [
            models.Index(fields=["name"], name="county_name_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(latitude__isnull=True)
                    | (
                        models.Q(latitude__gte=Decimal("-90"))
                        & models.Q(latitude__lte=Decimal("90"))
                    )
                ),
                name="county_latitude_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(longitude__isnull=True)
                    | (
                        models.Q(longitude__gte=Decimal("-180"))
                        & models.Q(longitude__lte=Decimal("180"))
                    )
                ),
                name="county_longitude_range",
            ),
        ]

    def __str__(self):
        return self.name


class EnvironmentalObservation(models.Model):
    class Source(models.TextChoices):
        NASA_POWER = "NASA_POWER", "NASA POWER"
        IMPORTED = "IMPORTED", "Imported historical data"
        MANUAL = "MANUAL", "Manual entry"

    county = models.ForeignKey(
        County,
        on_delete=models.PROTECT,
        related_name="environmental_observations",
    )
    observation_date = models.DateField()

    precipitation_max_mm = models.DecimalField(
        max_digits=10,
        decimal_places=3,
    )
    temperature_mean_c = models.DecimalField(
        max_digits=6,
        decimal_places=2,
    )
    relative_humidity_mean_pct = models.DecimalField(
        max_digits=6,
        decimal_places=3,
    )
    soil_wetness_mean_fraction = models.DecimalField(
        max_digits=8,
        decimal_places=6,
    )
    soil_wetness_max_fraction = models.DecimalField(
        max_digits=8,
        decimal_places=6,
    )
    month_sin = models.DecimalField(
        max_digits=10,
        decimal_places=8,
    )
    month_cos = models.DecimalField(
        max_digits=10,
        decimal_places=8,
    )

    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.NASA_POWER,
    )
    source_record_id = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )
    is_synthetic = models.BooleanField(default=False)
    quality_review_required = models.BooleanField(default=False)
    ingested_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-observation_date", "county__name"]
        indexes = [
            models.Index(
                fields=["observation_date"],
                name="observation_date_idx",
            ),
            models.Index(
                fields=["source"],
                name="observation_source_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["county", "observation_date"],
                name="unique_county_observation_date",
            ),
            models.CheckConstraint(
                condition=models.Q(precipitation_max_mm__gte=Decimal("0")),
                name="observation_precipitation_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(temperature_mean_c__gte=Decimal("-100"))
                    & models.Q(temperature_mean_c__lte=Decimal("100"))
                ),
                name="observation_temperature_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(relative_humidity_mean_pct__gte=Decimal("0"))
                    & models.Q(relative_humidity_mean_pct__lte=Decimal("100"))
                ),
                name="observation_humidity_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        soil_wetness_mean_fraction__gte=Decimal("0")
                    )
                    & models.Q(
                        soil_wetness_mean_fraction__lte=Decimal("1")
                    )
                ),
                name="observation_soil_mean_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        soil_wetness_max_fraction__gte=Decimal("0")
                    )
                    & models.Q(
                        soil_wetness_max_fraction__lte=Decimal("1")
                    )
                ),
                name="observation_soil_max_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    soil_wetness_max_fraction__gte=models.F(
                        "soil_wetness_mean_fraction"
                    )
                ),
                name="observation_soil_max_gte_mean",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(month_sin__gte=Decimal("-1"))
                    & models.Q(month_sin__lte=Decimal("1"))
                ),
                name="observation_month_sin_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(month_cos__gte=Decimal("-1"))
                    & models.Q(month_cos__lte=Decimal("1"))
                ),
                name="observation_month_cos_range",
            ),
        ]

    def __str__(self):
        return f"{self.county.name} — {self.observation_date}"


class FloodPrediction(models.Model):
    class RiskLevel(models.TextChoices):
        LOW = "Low", "Low"
        MEDIUM = "Medium", "Medium"
        HIGH = "High", "High"

    observation = models.ForeignKey(
        EnvironmentalObservation,
        on_delete=models.PROTECT,
        related_name="predictions",
    )
    risk_level = models.CharField(
        max_length=10,
        choices=RiskLevel.choices,
    )

    probability_low = models.DecimalField(
        max_digits=7,
        decimal_places=6,
    )
    probability_medium = models.DecimalField(
        max_digits=7,
        decimal_places=6,
    )
    probability_high = models.DecimalField(
        max_digits=7,
        decimal_places=6,
    )

    model_release_id = models.CharField(max_length=100)
    decision_rule = models.CharField(max_length=100)
    high_probability_threshold = models.DecimalField(
        max_digits=7,
        decimal_places=6,
        default=Decimal("0.440000"),
    )
    predicted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observation__observation_date", "observation__county__name"]
        indexes = [
            models.Index(
                fields=["risk_level", "predicted_at"],
                name="prediction_risk_date_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["observation", "model_release_id"],
                name="unique_observation_model_release",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    risk_level__in=["Low", "Medium", "High"]
                ),
                name="prediction_risk_level_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(probability_low__gte=Decimal("0"))
                    & models.Q(probability_low__lte=Decimal("1"))
                ),
                name="prediction_low_probability_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(probability_medium__gte=Decimal("0"))
                    & models.Q(probability_medium__lte=Decimal("1"))
                ),
                name="prediction_medium_probability_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(probability_high__gte=Decimal("0"))
                    & models.Q(probability_high__lte=Decimal("1"))
                ),
                name="prediction_high_probability_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(high_probability_threshold__gte=Decimal("0"))
                    & models.Q(high_probability_threshold__lte=Decimal("1"))
                ),
                name="prediction_high_threshold_range",
            ),
        ]

    @property
    def county(self):
        return self.observation.county

    def clean(self):
        super().clean()

        probabilities = (
            self.probability_low,
            self.probability_medium,
            self.probability_high,
        )

        if any(value is None for value in probabilities):
            return

        probability_total = sum(probabilities, Decimal("0"))

        if abs(probability_total - Decimal("1")) > Decimal("0.000001"):
            raise ValidationError(
                {
                    "probability_high": (
                        "Low, Medium and High probabilities must sum to 1."
                    )
                }
            )

    def __str__(self):
        return (
            f"{self.observation.county.name} — "
            f"{self.observation.observation_date} — "
            f"{self.risk_level}"
        )


class AlertNotification(models.Model):
    class Channel(models.TextChoices):
        IN_APP = "IN_APP", "In-app"
        EMAIL = "EMAIL", "Email"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    prediction = models.ForeignKey(
        FloodPrediction,
        on_delete=models.PROTECT,
        related_name="alerts",
    )
    channel = models.CharField(
        max_length=20,
        choices=Channel.choices,
        default=Channel.IN_APP,
    )
    recipient = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )
    message = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    failure_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="alert_status_date_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["prediction", "channel", "recipient"],
                name="unique_prediction_alert_recipient",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="SENT")
                    | models.Q(sent_at__isnull=False)
                ),
                name="sent_alert_requires_timestamp",
            ),
        ]

    def __str__(self):
        return (
            f"{self.prediction.observation.county.name} — "
            f"{self.channel} — {self.status}"
        )