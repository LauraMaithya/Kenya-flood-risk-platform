from django.urls import path

from monitoring.api_views import (
    AlertNotificationListAPIView,
    CountyDetailAPIView,
    CountyListAPIView,
    EnvironmentalObservationListAPIView,
    FloodPredictionListAPIView,
    HealthAPIView,
)

from monitoring.auth_views import (
    CSRFTokenAPIView,
    CurrentUserAPIView,
    LoginAPIView,
    LogoutAPIView,
    RegisterAPIView,
)

app_name = "monitoring-api"

urlpatterns = [
    path("health/", HealthAPIView.as_view(), name="health"),
    path(
        "counties/",
        CountyListAPIView.as_view(),
        name="county-list",
    ),
    path(
        "counties/<slug:slug>/",
        CountyDetailAPIView.as_view(),
        name="county-detail",
    ),
    path(
        "observations/",
        EnvironmentalObservationListAPIView.as_view(),
        name="observation-list",
    ),
    path(
        "predictions/",
        FloodPredictionListAPIView.as_view(),
        name="prediction-list",
    ),
    path(
        "alerts/",
        AlertNotificationListAPIView.as_view(),
        name="alert-list",
    ),

        path(
        "auth/csrf/",
        CSRFTokenAPIView.as_view(),
        name="auth-csrf",
    ),
    path(
        "auth/register/",
        RegisterAPIView.as_view(),
        name="auth-register",
    ),
    path(
        "auth/login/",
        LoginAPIView.as_view(),
        name="auth-login",
    ),
    path(
        "auth/logout/",
        LogoutAPIView.as_view(),
        name="auth-logout",
    ),
    path(
        "auth/me/",
        CurrentUserAPIView.as_view(),
        name="auth-me",
    ),
]