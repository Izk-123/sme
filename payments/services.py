"""
payments/services.py

subscriptions/views.py calls into here, never into
payments.gateways.paychangu directly - see the design discussion's
`subscriptions -> payment service -> gateway adapter -> PayChangu` rule.
"""
import logging

from django.urls import reverse

from .gateways.paychangu import PayChanguGateway
from .models import PaymentTransaction

logger = logging.getLogger(__name__)


def get_gateway():
    """One place to change which gateway is active - swap this for a
    Flutterwave adapter later without touching any caller."""
    return PayChanguGateway()


def start_subscription_checkout(request, subscription, plan):
    """
    Creates a pending PaymentTransaction and returns the URL to redirect
    the customer to. Amount charged is the plan's monthly price - no
    proration/annual billing wired up yet (see SUBSCRIPTIONS_README.md).
    """
    transaction = PaymentTransaction.objects.create(
        subscription=subscription,
        plan=plan,
        amount=plan.price_monthly,
        currency="MWK",
    )

    membership = subscription.organization.memberships.filter(role__slug="owner", is_active=True).first()
    owner = membership.user if membership else request.user
    profile = getattr(owner, "profile", None)

    gateway = get_gateway()
    result = gateway.initiate_checkout(
        amount=plan.price_monthly,
        currency="MWK",
        tx_ref=transaction.tx_ref,
        email=owner.email,
        first_name=(profile.first_name if profile and profile.first_name else owner.username),
        last_name=(profile.last_name if profile else ""),
        callback_url=request.build_absolute_uri(reverse("payment_callback")),
        return_url=request.build_absolute_uri(reverse("payment_return")),
        title=f"{plan.name} plan - {subscription.organization.name}",
        description=f"Monthly subscription: {plan.name}",
        meta={"subscription_id": subscription.pk, "plan_id": plan.pk},
    )
    return result["checkout_url"]


def verify_and_apply(tx_ref):
    """
    The one place that turns "PayChangu says this succeeded" into
    "the subscription is actually extended". Called from both the
    callback view (customer just came back from checkout) and the
    webhook view (PayChangu telling us asynchronously) - safe to call
    from both, and safe to call twice, because of the `applied` guard.

    Returns the PaymentTransaction, or None if tx_ref is unknown.
    """
    transaction = PaymentTransaction.objects.select_related("subscription", "plan").filter(tx_ref=tx_ref).first()
    if transaction is None:
        logger.warning("verify_and_apply: unknown tx_ref %s", tx_ref)
        return None

    if transaction.applied:
        return transaction  # already handled - webhook retry, or callback+webhook both firing

    gateway = get_gateway()
    result = gateway.verify_transaction(tx_ref)
    transaction.raw_verification = result["raw"]

    # PayChangu's own docs list exactly these checks before trusting a
    # transaction - reference matches, status success, currency matches,
    # amount at least what was expected.
    verified_ok = (
        result["tx_ref"] == transaction.tx_ref
        and result["status"] == "success"
        and result["currency"] == transaction.currency
        and result["amount"] is not None
        and float(result["amount"]) >= float(transaction.amount)
    )

    if not verified_ok:
        transaction.status = "failed"
        transaction.save(update_fields=["status", "raw_verification", "updated_at"])
        return transaction

    transaction.status = "success"
    transaction.applied = True
    transaction.save(update_fields=["status", "applied", "raw_verification", "updated_at"])

    from subscriptions.services import apply_gateway_payment
    apply_gateway_payment(transaction.subscription, transaction.plan, transaction.amount, provider_ref=tx_ref)

    return transaction
