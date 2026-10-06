from datetime import date
from django.db.models import OuterRef, Subquery
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import ValidationError
from rest_framework.generics import (
    ListAPIView,
    RetrieveAPIView,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from monitoring.models import (
    AlertNotification,
    County,
    EnvironmentalObservation,
    FloodPrediction,
)
from monitoring.serializers import (
    AlertNotificationSerializer,
    CountySerializer,
    EnvironmentalObservationSerializer,
    FloodPredictionSerializer,
)


def _parse_date_parameter(request, parameter):
    value = request.query_params.get(parameter)

    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(
            {parameter: "Use the YYYY-MM-DD date format."}
        ) from exc


class HealthAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "status": "ok",
                "service": "Kenya Flood Risk Platform API",
            }
        )

class DashboardMapAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        latest_prediction = (
            FloodPrediction.objects.filter(
                observation__county_id=OuterRef("pk"),
                observation__is_synthetic=False,
            )
            .order_by(
                "-observation__observation_date",
                "-predicted_at",
                "-pk",
            )
            .values("pk")[:1]
        )

        counties = list(
            County.objects.annotate(
                latest_prediction_id=Subquery(
                    latest_prediction
                )
            ).order_by("name")
        )

        prediction_ids = [
            county.latest_prediction_id
            for county in counties
            if county.latest_prediction_id is not None
        ]

        predictions = (
            FloodPrediction.objects.select_related(
                "observation__county"
            )
            .filter(pk__in=prediction_ids)
        )

        predictions_by_id = {
            prediction.pk: prediction
            for prediction in predictions
        }

        results = []

        for county in counties:
            prediction = predictions_by_id.get(
                county.latest_prediction_id
            )

            item = {
                "county_id": county.pk,
                "county_code": county.code,
                "county_name": county.name,
                "county_slug": county.slug,
                "latitude": (
                    float(county.latitude)
                    if county.latitude is not None
                    else None
                ),
                "longitude": (
                    float(county.longitude)
                    if county.longitude is not None
                    else None
                ),
                "has_coordinates": (
                    county.latitude is not None
                    and county.longitude is not None
                ),
                "has_nasa_power_coverage": (
                    county.has_nasa_power_coverage
                ),
                "data_status": "NO_DATA",
                "risk_level": None,
                "observation_date": None,
                "probability_high": None,
                "model_release_id": None,
            }

            if prediction is not None:
                item.update(
                    {
                        "data_status": "AVAILABLE",
                        "risk_level": prediction.risk_level,
                        "observation_date": (
                            prediction.observation
                            .observation_date.isoformat()
                        ),
                        "probability_high": float(
                            prediction.probability_high
                        ),
                        "model_release_id": (
                            prediction.model_release_id
                        ),
                    }
                )

            results.append(item)

        return Response(
            {
                "count": len(results),
                "results": results,
            }
        )


class CountyListAPIView(ListAPIView):
    serializer_class = CountySerializer
    queryset = County.objects.order_by("name")


class CountyDetailAPIView(RetrieveAPIView):
    serializer_class = CountySerializer
    queryset = County.objects.all()
    lookup_field = "slug"


class EnvironmentalObservationListAPIView(ListAPIView):
    serializer_class = EnvironmentalObservationSerializer

    def get_queryset(self):
        queryset = (
            EnvironmentalObservation.objects.select_related(
                "county"
            )
            .filter(is_synthetic=False)
            .order_by("-observation_date", "county__name")
        )

        county = self.request.query_params.get("county")
        date_from = _parse_date_parameter(
            self.request,
            "date_from",
        )
        date_to = _parse_date_parameter(
            self.request,
            "date_to",
        )

        if county:
            queryset = queryset.filter(county__code=county)

        if date_from:
            queryset = queryset.filter(
                observation_date__gte=date_from
            )

        if date_to:
            queryset = queryset.filter(
                observation_date__lte=date_to
            )

        return queryset


class FloodPredictionListAPIView(ListAPIView):
    serializer_class = FloodPredictionSerializer

    def get_queryset(self):
        queryset = (
            FloodPrediction.objects.select_related(
                "observation__county"
            )
            .filter(observation__is_synthetic=False)
            .order_by(
                "-observation__observation_date",
                "observation__county__name",
            )
        )

        county = self.request.query_params.get("county")
        risk_level = self.request.query_params.get(
            "risk_level"
        )
        date_from = _parse_date_parameter(
            self.request,
            "date_from",
        )
        date_to = _parse_date_parameter(
            self.request,
            "date_to",
        )

        if county:
            queryset = queryset.filter(
                observation__county__code=county
            )

        if risk_level:
            if risk_level not in {"Low", "Medium", "High"}:
                raise ValidationError(
                    {
                        "risk_level": (
                            "Use Low, Medium or High."
                        )
                    }
                )
            queryset = queryset.filter(risk_level=risk_level)

        if date_from:
            queryset = queryset.filter(
                observation__observation_date__gte=date_from
            )

        if date_to:
            queryset = queryset.filter(
                observation__observation_date__lte=date_to
            )

        return queryset


class AlertNotificationListAPIView(ListAPIView):
    serializer_class = AlertNotificationSerializer

    def get_queryset(self):
        queryset = (
            AlertNotification.objects.select_related(
                "prediction__observation__county"
            )
            .filter(
                prediction__observation__is_synthetic=False
            )
            .order_by("-created_at")
        )

        county = self.request.query_params.get("county")
        channel = self.request.query_params.get("channel")
        status = self.request.query_params.get("status")

        if county:
            queryset = queryset.filter(
                prediction__observation__county__code=county
            )

        if channel:
            if channel not in {"IN_APP", "EMAIL"}:
                raise ValidationError(
                    {"channel": "Use IN_APP or EMAIL."}
                )
            queryset = queryset.filter(channel=channel)

        if status:
            if status not in {"PENDING", "SENT", "FAILED"}:
                raise ValidationError(
                    {
                        "status": (
                            "Use PENDING, SENT or FAILED."
                        )
                    }
                )
            queryset = queryset.filter(status=status)

        return queryset