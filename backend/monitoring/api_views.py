from datetime import date
from rest_framework.permissions import AllowAny
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