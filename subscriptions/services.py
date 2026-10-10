"""
subscriptions/services.py

Single entry point for anything that needs to know about an
organization's subscription - views should call these functions
instead of poking Subscription/SubscriptionPlan directly, so feature
gating stays `has_feature("barcode")` everywhere instead of
`if plan.slug == "business"` scattered across the codebase.

No payment gateway is integrated yet (PayChangu was mentioned as a
candidate in the design discussion, for Malawi mobile-money support -
Airtel Money / TNM Mpamba). Until that exists, `record_manual_payment`
below is how a paid period gets applied - meant for an admin/owner
entering a payment they received outside the system (bank transfer,
mobile money manually confirmed), not for a checkout flow.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from .models import (
    DEFAULT_TRIAL_DAYS,
    DEFAULT_TRIAL_PLAN_SLUG,
    Invoice,
    Payment,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)


def get_subscription(organization):
    """Safe get-or-create: any Organization created before this app
    existed (or created some other way) still gets a usable
    subscription. Also refreshes lifecycle status on every read - see
    Subscription.refresh_status()."""
    subscription = getattr(organization, "subscription", None)
    if subscription is None:
        free_plan = SubscriptionPlan.objects.filter(slug="free").first()
        if free_plan is None:
            raise SubscriptionPlan.DoesNotExist(
                "No 'free' SubscriptionPlan exists - run `python manage.py seed_plans` first."
            )
        subscription = Subscription.objects.create(
            organization=organization,
            plan=free_plan,
            status=SubscriptionStatus.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=36500),  # Free doesn't expire
        )
    subscription.refresh_status()
    return subscription


def start_trial(organization, plan_slug=DEFAULT_TRIAL_PLAN_SLUG, days=DEFAULT_TRIAL_DAYS):
    """Called from subscriptions/signals.py when a new Organization is
    created - every new business gets a full-featured trial rather than
    starting on Free (see the design discussion's "let them see value
    first" reasoning)."""
    plan = SubscriptionPlan.objects.filter(slug=plan_slug).first()
    if plan is None:
        plan = SubscriptionPlan.objects.filter(slug="free").first()
    return Subscription.objects.create(
        organization=organization,
        plan=plan,
        status=SubscriptionStatus.TRIALING,
        trial_end=timezone.now() + timedelta(days=days),
    )


def has_feature(organization, feature_name):
    return get_subscription(organization).has_feature(feature_name)


def check_usage_limits(organization):
    """Returns a list of {field, label, count, limit} dicts for any
    limit that's currently exceeded - callers decide how to surface
    that (banner, blocking a specific action, etc.)."""
    subscription = get_subscription(organization)
    plan = subscription.plan
    warnings = []

    user_count = organization.memberships.filter(is_active=True).count()
    user_limit = plan.get_limit("max_users")
    if user_limit is not None and user_count > user_limit:
        warnings.append({"field": "max_users", "label": "team members", "count": user_count, "limit": user_limit})

    if hasattr(organization, "products"):
        product_count = organization.products.count()
        product_limit = plan.get_limit("max_products")
        if product_limit is not None and product_count > product_limit:
            warnings.append({"field": "max_products", "label": "products", "count": product_count, "limit": product_limit})

    if hasattr(organization, "sales"):
        month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        tx_limit = plan.get_limit("max_transactions_month")
        if tx_limit is not None:
            tx_count = organization.sales.filter(created_at__gte=month_start).count()
            if tx_count > tx_limit:
                warnings.append({
                    "field": "max_transactions_month", "label": "transactions this month",
                    "count": tx_count, "limit": tx_limit,
                })

    return warnings


def can_downgrade_to(organization, new_plan):
    """Returns (True, []) or (False, [reasons]) - see the design
    discussion's rule: never silently delete data/remove employees to
    fit a smaller plan, tell the owner what to reduce first."""
    reasons = []

    user_count = organization.memberships.filter(is_active=True).count()
    user_limit = new_plan.get_limit("max_users")
    if user_limit is not None and user_count > user_limit:
        reasons.append(f"You have {user_count} active team members - {new_plan.name} allows {user_limit}.")

    if hasattr(organization, "products"):
        product_count = organization.products.count()
        product_limit = new_plan.get_limit("max_products")
        if product_limit is not None and product_count > product_limit:
            reasons.append(f"You have {product_count} products - {new_plan.name} allows {product_limit}.")

    return (not reasons, reasons)


def upgrade_plan(organization, new_plan):
    """For an upgrade (more headroom), this always succeeds. For a
    downgrade, call can_downgrade_to() first - this function doesn't
    check that itself, since the view needs the reasons list to show
    the owner regardless of whether it blocks the change."""
    subscription = get_subscription(organization)
    subscription.plan = new_plan
    if subscription.status in (SubscriptionStatus.GRACE, SubscriptionStatus.RESTRICTED, SubscriptionStatus.CANCELLED):
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.current_period_end = timezone.now() + timedelta(days=30)
        subscription.grace_end = None
    subscription.save()
    return subscription


@transaction.atomic
def apply_gateway_payment(subscription, plan, amount, provider_ref="", period_days=30):
    """
    Called by payments.services.verify_and_apply() once PayChangu has
    confirmed a transaction really succeeded. Same effect as
    record_manual_payment, but for a gateway-verified payment rather
    than a manually-entered one - kept separate mainly so the audit
    trail (Payment.transaction_ref / payment_method) is honest about
    which happened.
    """
    now = timezone.now()
    invoice = Invoice.objects.create(
        subscription=subscription,
        invoice_number=f"INV-{now:%Y%m}-{get_random_string(6).upper()}",
        amount=amount,
        period_start=now.date(),
        period_end=(now + timedelta(days=period_days)).date(),
        status="paid",
    )
    Payment.objects.create(
        invoice=invoice,
        amount=amount,
        payment_method="other",  # PayChangu abstracts Airtel/Mpamba/card - see Payment.transaction_ref for the reference
        transaction_ref=provider_ref,
        status="success",
    )
    subscription.plan = plan
    subscription.save(update_fields=["plan"])
    subscription.start_period(days=period_days)
    return invoice


@transaction.atomic
def record_manual_payment(subscription, amount, payment_method, transaction_ref="", period_days=30):
    """Owner (or staff, via /admin/) confirms a payment was received
    outside the system. Creates the Invoice + Payment pair and extends
    the subscription's current period - this is the manual stand-in
    for what a payment gateway webhook would do automatically."""
    now = timezone.now()
    invoice = Invoice.objects.create(
        subscription=subscription,
        invoice_number=f"INV-{now:%Y%m}-{get_random_string(6).upper()}",
        amount=amount,
        period_start=now.date(),
        period_end=(now + timedelta(days=period_days)).date(),
        status="paid",
    )
    Payment.objects.create(
        invoice=invoice,
        amount=amount,
        payment_method=payment_method,
        transaction_ref=transaction_ref,
        status="success",
    )
    subscription.start_period(days=period_days)
    return invoice
