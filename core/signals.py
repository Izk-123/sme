# core/signals.py
"""
Signal handlers that trigger notifications on key events.
All external calls (Redis, email, SMS) are wrapped in try/except
to prevent them from breaking the main transaction.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.urls import reverse
from sales.models import Sale
from .models import Notification
from .services import send_notification

# Set up logging so we can see errors in the console/logs
logger = logging.getLogger(__name__)


@receiver(post_save, sender=Sale)
def notify_sale_created(sender, instance, created, **kwargs):
    """
    When a new sale is created, notify all owners of that organization.
    - Saves a Notification record in the database.
    - Sends a real‑time WebSocket message (if Redis is available).
    - Sends email/SMS/WhatsApp via send_notification() (if configured).
    """
    if not created:
        return

    # Only proceed if the sale has an organization
    if not instance.organization:
        return

    from accounts.models import Membership

    # Find all users with the 'owner' role in this organization
    owners = Membership.objects.filter(
        organization=instance.organization,
        role__slug='owner'
    )

    # Get the channel layer for WebSocket notifications
    try:
        channel_layer = get_channel_layer()
    except Exception as e:
        logger.warning(f"Could not get channel layer: {e}")
        channel_layer = None

    for membership in owners:
        user = membership.user
        try:
            # 1. Save notification to database
            notif = Notification.objects.create(
                recipient=user,
                organization=instance.organization,
                title="New Sale Recorded",
                message=f"Sale #{instance.id} worth MK{instance.total} recorded.",
                notification_type="success",
                action_url=reverse('sale_list')
            )

            # 2. Send via channels (email/SMS/WhatsApp) – this may also try Redis
            try:
                send_notification(notif)
            except Exception as e:
                logger.error(f"Failed to send multi‑channel notification for sale #{instance.id}: {e}")

            # 3. Send real‑time WebSocket message (if Redis is available)
            if channel_layer:
                try:
                    async_to_sync(channel_layer.group_send)(
                        f"user_{user.id}",
                        {
                            "type": "send_notification",
                            "notification_type": "success",
                            "title": notif.title,
                            "message": notif.message,
                            "action_url": notif.action_url,
                            "notification_id": notif.id
                        }
                    )
                except Exception as e:
                    logger.error(f"WebSocket notification failed for user {user.id}: {e}")
            else:
                logger.info("Channel layer not available – skipping WebSocket notification.")

        except Exception as e:
            # Catch any other error (e.g., DB issue) so the sale still completes
            logger.error(f"Unexpected error in notify_sale_created for user {user.id}: {e}")

    # The sale always completes – no error is raised.