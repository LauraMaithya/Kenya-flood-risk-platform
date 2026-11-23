from monitoring.models import AlertNotification, MonthlyOutlookAdvisory


def alert_navigation(request):
    if not request.user.is_authenticated:
        return {"unacknowledged_alert_count": 0}

    daily_count = AlertNotification.objects.filter(
        channel=AlertNotification.Channel.IN_APP,
        is_test=False,
        acknowledged_at__isnull=True,
        prediction__observation__is_synthetic=False,
    ).count()
    outlook_count = MonthlyOutlookAdvisory.objects.filter(
        channel=AlertNotification.Channel.IN_APP,
        acknowledged_at__isnull=True,
    ).count()

    return {
        "unacknowledged_alert_count": daily_count + outlook_count
    }
