from django.db.models import Count, Q

from monitoring.models import AlertNotification


def alert_notification_queryset(filters=None):
    queryset = (
        AlertNotification.objects.select_related(
            "prediction__observation__county"
        )
        .filter(
            prediction__observation__is_synthetic=False
        )
        .order_by("-created_at", "-pk")
    )

    if not filters:
        return queryset

    county = filters.get("county")
    channel = filters.get("channel")
    status = filters.get("status")

    if county:
        queryset = queryset.filter(
            prediction__observation__county=county
        )

    if channel:
        queryset = queryset.filter(channel=channel)

    if status:
        queryset = queryset.filter(status=status)

    return queryset


def alert_status_summary(queryset):
    return queryset.aggregate(
        total_alert_count=Count("pk"),
        pending_alert_count=Count(
            "pk",
            filter=Q(
                status=AlertNotification.Status.PENDING
            ),
        ),
        sent_alert_count=Count(
            "pk",
            filter=Q(
                status=AlertNotification.Status.SENT
            ),
        ),
        failed_alert_count=Count(
            "pk",
            filter=Q(
                status=AlertNotification.Status.FAILED
            ),
        ),
    )