from django.urls import path

from monitoring.web_views import (
    AlertAcknowledgeView,
    AlertsPageView,
    CountyRiskView,
    DashboardView,
    HistoricalDataDownloadView,
    HistoricalDataView,
    LoginPageView,
    OutlookAdvisoryAcknowledgeView,
    ProfilePageView,
    RegisterPageView,
    RootRedirectView,
)


app_name = "monitoring-web"

urlpatterns = [
    path("", RootRedirectView.as_view(), name="root"),
    path(
        "login/",
        LoginPageView.as_view(),
        name="login",
    ),
    path(
        "register/",
        RegisterPageView.as_view(),
        name="register",
    ),
    path(
        "dashboard/",
        DashboardView.as_view(),
        name="dashboard",
    ),
    path(
        "county-risk/",
        CountyRiskView.as_view(),
        name="county-risk",
    ),
    path(
        "historical-data/",
        HistoricalDataView.as_view(),
        name="historical-data",
    ),
    path(
    "historical-data/download/",
    HistoricalDataDownloadView.as_view(),
    name="historical-data-download",
    ),
    path(
        "alerts/",
        AlertsPageView.as_view(),
        name="alerts",
    ),
    path(
        "alerts/<int:pk>/acknowledge/",
        AlertAcknowledgeView.as_view(),
        name="alert-acknowledge",
    ),
    path(
        "alerts/outlook/<int:pk>/acknowledge/",
        OutlookAdvisoryAcknowledgeView.as_view(),
        name="outlook-advisory-acknowledge",
    ),
    path(
        "profile/",
        ProfilePageView.as_view(),
        name="profile",
    ),
]
