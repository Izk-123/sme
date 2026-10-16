# core/signals.py
"""
Signal handlers that trigger notifications on key events.

Design goals:
  * Never let a notification failure break the primary transaction
    (a sale must always be recorded, even if email/SMS/WebSocket is down).
  * Keep DB writes aligned with the Notification model's actual fields.
  * Degrade gracefully when Redis / channel layer is unavailable.

Anything that touches the outside world — Redis, SMTP, SMS gateway — is
wrapped in try/except and logged, never raised.
"""

from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

from sales.models import Sale

from .models import Notification
from .services import send_notification

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sale_action_url(sale: Sale) -> str:
    """
    Best-effort URL for 'click this notification to see the sale'.

    Prefers a named detail view if one exists; falls back to the list view;
    falls back to '/' if neither reverse() resolves.
    """
    for name in ("sale_detail", "sale_list"):
        try:
            # If the view expects a pk, only sale_detail would resolve;
            # sale_list takes no args, so we try both signatures.
            if name == "sale_detail":
                return reverse(name, args=[sale.pk])
            return reverse(name)
        except Exception:
            continue
    return "/"


def _push_websocket(user_id: int, notif: Notification) -> None:
    """
    Send the real-time notification payload over the channel layer.

    Silently no-ops if Redis / the channel layer is not configured.
    """
    try:
        channel_layer = get_channel_layer()
    except Exception as exc:
        logger.warning("Channel layer unavailable: %s", exc)
        return

    if channel_layer is None:
        logger.info("No channel layer configured — skipping WebSocket push.")
        return

    try:
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            {
                "type": "send_notification",
                # The frontend expects this shape; keep these keys stable.
                "notification_id": notif.id,
                "title": notif.title,
                "message": notif.message,
                "level": notif.level,
                "url": notif.url,
            },
        )
    except Exception as exc:
        logger.error("WebSocket push failed for user %s: %s", user_id, exc)


# ---------------------------------------------------------------------------
# Signal: new Sale created
# ---------------------------------------------------------------------------

@receiver(post_save, sender=Sale)
def notify_sale_created(sender, instance: Sale, created: bool, **kwargs) -> None:
    """
    Notify every owner of the sale's organization that a new sale landed.

    Performs three actions, each independent of the others:
      1. Persist a Notification row.
      2. Hand it off to core.services.send_notification() for
         email / SMS / WhatsApp delivery.
      3. Push it over WebSockets (if Redis is configured).
    """
    # Only react to inserts, not updates.
    if not created:
        return

    # A sale without an organization has no owners to notify.
    if not instance.organization_id:
        return

    # Imported here to avoid a circular import at module load time
    # (accounts imports core in some places).
    from accounts.models import Membership

    owners = (
        Membership.objects
        .filter(organization_id=instance.organization_id, role__slug="owner")
        .select_related("user")
    )

    action_url = _sale_action_url(instance)

    for membership in owners:
        user = membership.user

        # ---- 1. Persist the notification ----------------------------------
        try:
            notif = Notification.objects.create(
                recipient=user,
                title="New Sale Recorded",
                message=f"Sale #{instance.pk} worth MK{instance.total} recorded.",
                level="success",       # one of: info | success | warning | error
                url=action_url,
            )
        except Exception as exc:
            # If we can't even write the notification, don't bother with
            # the multi-channel send — but still log loudly.
            logger.error(
                "Failed to create Notification for user %s, sale #%s: %s",
                user.pk, instance.pk, exc,
            )
            continue

        # ---- 2. Multi-channel delivery (email / SMS / WhatsApp) -----------
        try:
            send_notification(notif)
        except Exception as exc:
            logger.error(
                "send_notification failed (user=%s, notif=%s): %s",
                user.pk, notif.pk, exc,
            )

        # ---- 3. Real-time WebSocket push ----------------------------------
        _push_websocket(user.pk, notif)

    # Note: exceptions are swallowed deliberately. A broken notification
    # pipeline must never roll back the sale that triggered it.