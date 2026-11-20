from django.db.models import Count, Q

from monitoring.models import AlertNotification


def alert_notification_queryset(filters=None):
    queryset = (
        AlertNotification.objects.select_related(
            "prediction__observation__county",
            "acknowledged_by",
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
    acknowledgement = filters.get("acknowledgement")

    if county:
        queryset = queryset.filter(
            prediction__observation__county=county
        )

    if channel:
        queryset = queryset.filter(channel=channel)

    if status:
        queryset = queryset.filter(status=status)

    if acknowledgement == "UNACKNOWLEDGED":
        queryset = queryset.filter(
            channel=AlertNotification.Channel.IN_APP,
            acknowledged_at__isnull=True,
        )
    elif acknowledgement == "ACKNOWLEDGED":
        queryset = queryset.filter(
            acknowledged_at__isnull=False
        )

    return queryset


def alert_status_summary(queryset):
    return queryset.filter(is_test=False).aggregate(
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
