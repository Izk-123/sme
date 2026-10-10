# core/models.py
from django.conf import settings
from django.db import models


class Notification(models.Model):
    """
    A single notification for one user. Read by
    core.consumers.NotificationConsumer over the WebSocket connection
    set up in core/routing.py + config/asgi.py.

    Kept user-scoped (not organization-scoped) to match exactly what the
    consumer already queries (`recipient=self.user`) - a notification
    about something happening at a business still goes to a specific
    person's inbox, same as email/SMS would.

    Nothing currently creates rows here except core/notifications.py's
    notify_user() helper - see that module for how to actually send one
    (creates the row AND pushes it over the channel layer in one call,
    so the real-time delivery loop is complete, not just the receiving
    half).
    """

    LEVEL_CHOICES = [
        ("info", "Info"),
        ("success", "Success"),
        ("warning", "Warning"),
        ("danger", "Danger"),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default="info")
    url = models.CharField(max_length=500, blank=True, help_text="Where clicking the notification should go.")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient}: {self.title}"
