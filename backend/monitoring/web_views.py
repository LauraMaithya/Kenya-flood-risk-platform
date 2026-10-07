import csv
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from monitoring.models import County, FloodPrediction
from django.core.paginator import Paginator
from django.http import HttpResponse
from monitoring.forms import (
    AlertFilterForm,
    CountyRiskFilterForm,
    HistoricalDataFilterForm,
)
from monitoring.services.historical_data import (
    historical_prediction_queryset,
)
from monitoring.services.alert_history import (
    alert_notification_queryset,
    alert_status_summary,
)
from monitoring.services.county_risk import (
    latest_county_prediction,
    recent_county_predictions,
)

class RootRedirectView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("monitoring-web:dashboard")

        return redirect("monitoring-web:login")


class PublicOnlyView(TemplateView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("monitoring-web:dashboard")

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        requested_next = self.request.GET.get("next", "")

        if requested_next and url_has_allowed_host_and_scheme(
            requested_next,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            context["success_url"] = requested_next
        else:
            context["success_url"] = reverse(
                "monitoring-web:dashboard"
            )

        return context


class LoginPageView(PublicOnlyView):
    template_name = "monitoring/login.html"


class RegisterPageView(PublicOnlyView):
    template_name = "monitoring/register.html"


def latest_prediction_summary():
    latest_prediction = (
        FloodPrediction.objects.filter(
            observation__county_id=OuterRef("pk")
        )
        .order_by(
            "-observation__observation_date",
            "-predicted_at",
            "-pk",
        )
        .values("pk")[:1]
    )

    latest_prediction_ids = (
        County.objects.annotate(
            latest_prediction_id=Subquery(latest_prediction)
        )
        .exclude(latest_prediction_id__isnull=True)
        .values("latest_prediction_id")
    )

    return FloodPrediction.objects.filter(
        pk__in=Subquery(latest_prediction_ids)
    ).aggregate(
        high_risk_count=Count(
            "pk",
            filter=Q(risk_level=FloodPrediction.RiskLevel.HIGH),
        ),
        medium_risk_count=Count(
            "pk",
            filter=Q(risk_level=FloodPrediction.RiskLevel.MEDIUM),
        ),
        low_risk_count=Count(
            "pk",
            filter=Q(risk_level=FloodPrediction.RiskLevel.LOW),
        ),
        monitored_count=Count("pk"),
        latest_data_date=Max(
            "observation__observation_date"
        ),
    )


class ProtectedPageView(LoginRequiredMixin, TemplateView):
    login_url = "monitoring-web:login"


class DashboardView(ProtectedPageView):
    template_name = "monitoring/dashboard.html"
    extra_context = {"page_title": "Dashboard"}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(latest_prediction_summary())
        return context


class CountyRiskView(ProtectedPageView):
    template_name = "monitoring/county_risk.html"
    extra_context = {"page_title": "County Risk"}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form_data = (
            self.request.GET
            if "county" in self.request.GET
            else None
        )
        form = CountyRiskFilterForm(form_data)

        selected_county = None
        latest_prediction = None
        recent_predictions = []

        if form.is_bound and form.is_valid():
            selected_county = form.cleaned_data["county"]
            latest_prediction = latest_county_prediction(
                selected_county
            )
            recent_predictions = recent_county_predictions(
                selected_county
            )

        context.update(
            {
                "county_form": form,
                "county_count": (
                    form.fields["county"].queryset.count()
                ),
                "selected_county": selected_county,
                "latest_prediction": latest_prediction,
                "latest_observation": (
                    latest_prediction.observation
                    if latest_prediction
                    else None
                ),
                "recent_predictions": recent_predictions,
            }
        )

        return context


class HistoricalDataView(ProtectedPageView):
    template_name = "monitoring/historical_data.html"
    extra_context = {
        "page_title": "Historical Data",
    }
    paginate_by = 25

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        form = HistoricalDataFilterForm(
            self.request.GET
        )

        if form.is_valid():
            predictions = historical_prediction_queryset(
                form.cleaned_data
            )
        else:
            predictions = FloodPrediction.objects.none()

        paginator = Paginator(
            predictions,
            self.paginate_by,
        )
        page_obj = paginator.get_page(
            self.request.GET.get("page")
        )

        download_parameters = (
            self.request.GET.copy()
        )
        download_parameters.pop("page", None)

        context.update(
            {
                "filter_form": form,
                "page_obj": page_obj,
                "predictions": page_obj.object_list,
                "result_count": paginator.count,
                "download_query": (
                    download_parameters.urlencode()
                ),
            }
        )

        return context

class HistoricalDataDownloadView(
    LoginRequiredMixin,
    View,
):
    login_url = "monitoring-web:login"

    def get(self, request):
        form = HistoricalDataFilterForm(
            request.GET
        )

        if not form.is_valid():
            return HttpResponse(
                "Invalid historical-data filters.",
                status=400,
                content_type="text/plain",
            )

        predictions = historical_prediction_queryset(
            form.cleaned_data
        )

        response = HttpResponse(
            content_type="text/csv",
        )
        response["Content-Disposition"] = (
            'attachment; filename="'
            'kenya_flood_risk_history.csv"'
        )

        writer = csv.writer(response)
        writer.writerow(
            [
                "county_code",
                "county_name",
                "observation_date",
                "risk_level",
                "probability_low",
                "probability_medium",
                "probability_high",
                "model_release_id",
                "decision_rule",
                "predicted_at",
            ]
        )

        for prediction in predictions.iterator():
            observation = prediction.observation
            county = observation.county

            writer.writerow(
                [
                    county.code,
                    county.name,
                    observation.observation_date.isoformat(),
                    prediction.risk_level,
                    prediction.probability_low,
                    prediction.probability_medium,
                    prediction.probability_high,
                    prediction.model_release_id,
                    prediction.decision_rule,
                    prediction.predicted_at.isoformat(),
                ]
            )

        return response


class AlertsPageView(ProtectedPageView):
    template_name = "monitoring/alerts.html"
    extra_context = {"page_title": "Alerts"}
    paginate_by = 25

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = AlertFilterForm(self.request.GET)

        if form.is_valid():
            alerts = alert_notification_queryset(
                form.cleaned_data
            )
        else:
            alerts = alert_notification_queryset().none()

        summary = alert_status_summary(alerts)
        paginator = Paginator(alerts, self.paginate_by)
        page_obj = paginator.get_page(
            self.request.GET.get("page")
        )

        pagination_parameters = self.request.GET.copy()
        pagination_parameters.pop("page", None)

        context.update(
            {
                "filter_form": form,
                "alerts": page_obj.object_list,
                "page_obj": page_obj,
                "result_count": paginator.count,
                "pagination_query": (
                    pagination_parameters.urlencode()
                ),
                **summary,
            }
        )

        return context


class ProfilePageView(ProtectedPageView):
    template_name = "monitoring/profile.html"
    extra_context = {"page_title": "User Profile"}