from monitoring.models import AlertNotification


def alert_navigation(request):
    if not request.user.is_authenticated:
        return {"unacknowledged_alert_count": 0}

    count = AlertNotification.objects.filter(
        channel=AlertNotification.Channel.IN_APP,
        is_test=False,
        acknowledged_at__isnull=True,
        prediction__observation__is_synthetic=False,
    ).count()

    return {"unacknowledged_alert_count": count}
