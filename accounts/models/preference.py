# accounts/models/preference.py
"""
Per-user preferences — appearance/locale (UserPreference) and
notification opt-ins (NotificationPreference).

Both are one-to-one with User and are auto-created by the post_save
signal in accounts/signals.py, so every code path can rely on the row
existing without a get_or_create dance at the call site. (The
get_or_create calls that DO exist — e.g. in core/views.py — are
defensive for users created before the signal was wired up.)
"""

from django.conf import settings
from django.db import models


class UserPreference(models.Model):
    """
    Personal appearance / locale settings, plus the two flags that
    drive first-login guidance.

    See core/getting_started.py for how the checklist is derived from
    business data, and core/views.py::GetStartedActionView for the
    endpoint that flips the two guidance flags.
    """

    THEME_CHOICES = [
        ("system", "System"),
        ("light", "Light"),
        ("dark", "Dark"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    theme = models.CharField(
        max_length=20,
        choices=THEME_CHOICES,
        default="system",
    )
    language = models.CharField(max_length=10, default="en")
    timezone = models.CharField(max_length=100, default="Africa/Blantyre")
    compact_mode = models.BooleanField(default=False)

    # ------------------------------------------------------------------
    # First-login guidance
    # ------------------------------------------------------------------
    #
    # `tour_seen`
    #   Set once the 3-slide welcome modal has been finished, skipped,
    #   or closed. Deliberately NOT shown again on subsequent logins —
    #   that's the whole point. Can be reset by the user via
    #   "Show welcome guide" in the header dropdown, which calls
    #   core.views.GetStartedActionView with action="restart".
    #
    # `getting_started_dismissed`
    #   Set when the owner clicks "Hide" on the dashboard checklist.
    #   Independent of `tour_seen` — a user can re-see the welcome
    #   modal without resurrecting the checklist, or vice versa. Also
    #   reset by the "restart" action.
    #
    # Both default to False, so a brand-new user (whose row is created
    # by the post_save signal) gets the full onboarding experience.
    # The data migration 0014_existing_users_have_seen_tour flips
    # tour_seen=True for users who predate this feature, so they don't
    # get greeted with an onboarding flow they've already used the app
    # past.
    tour_seen = models.BooleanField(default=False)
    getting_started_dismissed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} preferences"


class NotificationPreference(models.Model):
    """
    Per-user notification channel and event-type opt-ins.

    Note: the actual send logic (accounts/services.py, core/services.py)
    reads `email_notifications`, `push_notifications`, and the
    per-event flags below; the older `email_enabled` / `sms_enabled` /
    `whatsapp_enabled` fields were removed in migration 0008 and are
    not consulted anywhere.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )

    # Sales alerts
    daily_sales_summary = models.BooleanField(default=True)

    # Inventory alerts
    low_stock_alert = models.BooleanField(default=True)
    out_of_stock_alert = models.BooleanField(default=True)

    # Customer alerts
    payment_overdue = models.BooleanField(default=True)
    customer_payment_received = models.BooleanField(default=True)

    # Security alerts
    new_login_alert = models.BooleanField(default=True)
    password_changed_alert = models.BooleanField(default=True)

    # Channels
    push_notifications = models.BooleanField(default=True)
    email_notifications = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} notification settings"