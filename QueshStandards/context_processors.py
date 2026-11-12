from django.utils import timezone
from django.db.models import Count, Max, Q

from communications.models import Notification
from governance.services import has_permission


def workplace_context(request):
    if not request.user.is_authenticated:
        return {}
    notification_stats = Notification.objects.filter(user=request.user).aggregate(
        unread_count=Count("pk", filter=Q(is_read=False)),
        latest_id=Max("pk"),
    )
    return {
        "unread_notifications": notification_stats["unread_count"],
        "latest_notification_id": notification_stats["latest_id"] or 0,
        "now": timezone.now(),
        "can_manage_workspace": request.user.can_manage_workplace
        or has_permission(request.user, "USER_VIEW"),
    }
