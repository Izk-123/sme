# core/notifications.py
"""
The other half of core/consumers.py: that consumer can only forward
events it's told about, and until now nothing in the app ever called
`channel_layer.group_send` - the WebSocket plumbing existed with no
sender. This is that sender.

Safe to call even if Channels/Redis isn't reachable (falls back to just
saving the Notification row - the person will see it next time they
load a page that shows their notification list, just not instantly).
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Notification

logger = logging.getLogger(__name__)


def notify_user(user, title, message="", level="info", url=""):
    notification = Notification.objects.create(
        recipient=user, title=title, message=message, level=level, url=url,
    )

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return notification

    try:
        async_to_sync(channel_layer.group_send)(
            f"user_{user.id}",
            {
                "type": "send_notification",
                "id": notification.id,
                "title": title,
                "message": message,
                "level": level,
                "url": url,
            },
        )
    except Exception:
        # Real-time delivery is a nice-to-have, not load-bearing - the
        # row is already saved, so this failing shouldn't break whatever
        # business action triggered the notification in the first place.
        logger.exception("Failed to push live notification to user %s", user.id)

    return notification
