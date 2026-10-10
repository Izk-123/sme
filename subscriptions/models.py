"""
subscriptions/models.py

Core rule from the design discussion: the Organization subscribes, not
the User. Every Membership at a business shares that one subscription -
there's no per-seat billing model here (max_users is a plan *limit*,
not a per-user charge).

`0` in any of a plan's max_* fields means "unlimited" - see
SubscriptionPlan.get_limit() / services.check_usage_limits(). This
avoids sprinkling `if x is None` all over the codebase for the common
case (Business/Professional tiers advertise "unlimited products").
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from organizations.models import Organization

UNLIMITED = 0

# How long a subscription keeps working after it's due, before it's
# cut over to RESTRICTED (read-only). See Subscription.refresh_status().
GRACE_PERIOD_DAYS = 5
DEFAULT_TRIAL_DAYS = 14
DEFAULT_TRIAL_PLAN_SLUG = "business"


class SubscriptionPlan(models.Model):
    """A SaaS tier. `features` is a flat {slug: bool} map - see
    services.has_feature(). Keep new feature flags here, not as new
    model fields, so adding one doesn't need a migration."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    price_monthly = models.DecimalField(max_digits=12, decimal_places=2)
    price_annual = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_users = models.PositiveIntegerField(default=1, help_text="0 = unlimited")
    max_products = models.PositiveIntegerField(default=10, help_text="0 = unlimited")
    max_branches = models.PositiveIntegerField(default=1, help_text="0 = unlimited")
    max_transactions_month = models.PositiveIntegerField(default=50, help_text="0 = unlimited")
    features = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "price_monthly"]

    def has_feature(self, feature_name):
        return bool(self.features.get(feature_name, False))

    def get_limit(self, field_name):
        """0 means unlimited - returns None in that case so callers can
        just do `if limit is not None and count > limit`."""
        value = getattr(self, field_name)
        return None if value == UNLIMITED else value

    def __str__(self):
        return self.name


class SubscriptionStatus(models.TextChoices):
    TRIALING = "trialing", "Trialing"
    ACTIVE = "active", "Active"
    GRACE = "grace", "Grace Period"
    RESTRICTED = "restricted", "Restricted"
    CANCELLED = "cancelled", "Cancelled"


class Subscription(models.Model):
    """
    The business's subscription. One per Organization - every Membership
    at that business shares it. related_name="subscription" gives every
    Organization an `org.subscription` accessor (raises DoesNotExist if
    none exists - use subscriptions.services.get_subscription(org) for a
    safe get-or-create instead of touching this directly in views).
    """

    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=SubscriptionStatus.choices, default=SubscriptionStatus.TRIALING)
    trial_end = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    grace_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.organization.name} - {self.plan.name} ({self.status})"

    # ---------- lifecycle ----------
    # No task queue/cron exists in this project yet, so status is
    # refreshed lazily on read (see services.get_subscription) rather
    # than by a background worker. A `sweep_subscriptions` management
    # command is provided for anyone who wants to cron it anyway (e.g.
    # to send expiry-reminder emails, which DO need to run even if
    # nobody visits the site that day).
    def refresh_status(self, save=True):
        now = timezone.now()
        changed = False
        new_status = None

        if self.status == SubscriptionStatus.TRIALING and self.trial_end and now >= self.trial_end:
            self.status = SubscriptionStatus.GRACE
            self.grace_end = now + timedelta(days=GRACE_PERIOD_DAYS)
            changed = True
            new_status = SubscriptionStatus.GRACE

        elif self.status == SubscriptionStatus.ACTIVE and self.current_period_end and now >= self.current_period_end:
            self.status = SubscriptionStatus.GRACE
            self.grace_end = now + timedelta(days=GRACE_PERIOD_DAYS)
            changed = True
            new_status = SubscriptionStatus.GRACE

        elif self.status == SubscriptionStatus.GRACE and self.grace_end and now >= self.grace_end:
            self.status = SubscriptionStatus.RESTRICTED
            changed = True
            new_status = SubscriptionStatus.RESTRICTED

        if changed and save:
            self.save(update_fields=["status", "grace_end", "updated_at"])
        if changed and new_status:
            self._notify_owner_of_status_change(new_status)
        return changed

    def _notify_owner_of_status_change(self, new_status):
        # Deferred import - core doesn't need to know about subscriptions,
        # only the other way around, so this stays a one-directional
        # dependency rather than a module-level circular one.
        from core.notifications import notify_user

        membership = self.organization.memberships.filter(role__slug="owner", is_active=True).first()
        if not membership:
            return

        if new_status == SubscriptionStatus.GRACE:
            notify_user(
                membership.user,
                title="Your subscription needs renewing",
                message=f"{self.organization.name}'s {self.plan.name} plan has expired. "
                        f"You have until {self.grace_end:%d %b} before new records are disabled.",
                level="warning",
                url="/subscriptions/",
            )
        elif new_status == SubscriptionStatus.RESTRICTED:
            notify_user(
                membership.user,
                title="Account restricted",
                message=f"{self.organization.name} is now in read-only mode. Renew to add new sales, "
                        f"stock, and employees again - your existing data is safe.",
                level="danger",
                url="/subscriptions/upgrade/",
            )

    @property
    def can_write(self):
        """False = read-only mode (see the design doc's "don't delete
        data, restrict writes" rule). Checked by
        core.permissions-style mixins in views that create/edit data."""
        return self.status not in (SubscriptionStatus.RESTRICTED, SubscriptionStatus.CANCELLED)

    @property
    def is_trialing(self):
        return self.status == SubscriptionStatus.TRIALING

    @property
    def days_remaining_in_trial(self):
        if not self.is_trialing or not self.trial_end:
            return 0
        return max((self.trial_end - timezone.now()).days, 0)

    def has_feature(self, feature_name):
        return self.plan.has_feature(feature_name)

    def start_period(self, days=30):
        self.status = SubscriptionStatus.ACTIVE
        self.current_period_end = timezone.now() + timedelta(days=days)
        self.grace_end = None
        self.save(update_fields=["status", "current_period_end", "grace_end", "updated_at"])


class Invoice(models.Model):
    """A billing record for one subscription period."""

    STATUS_CHOICES = [("pending", "Pending"), ("paid", "Paid"), ("failed", "Failed")]

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="invoices")
    invoice_number = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.amount}"


class Payment(models.Model):
    """A payment applied against an invoice. No gateway is wired up yet
    (see subscriptions/services.py's module docstring) - these are
    entered manually (e.g. via /admin/) until PayChangu or similar is
    integrated. transaction_ref is where that gateway's reference goes
    once one exists."""

    METHOD_CHOICES = [
        ("airtel_money", "Airtel Money"),
        ("tnm_mpamba", "TNM Mpamba"),
        ("bank", "Bank"),
        ("card", "Card"),
        ("other", "Other"),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    transaction_ref = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, default="success")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment {self.amount} for {self.invoice}"
