"""
payments/models.py

The payment layer is deliberately narrow right now: it only knows how
to record a subscription checkout attempt against PayChangu. That is
intentional - see the design discussion's rule about not building
generality before there's a second real use case. When customer or
supplier payments get added later, this model will be widened (probably
to a generic FK, or a separate model alongside this one), not replaced.
"""

import uuid

from django.db import models
from subscriptions.models import Subscription, SubscriptionPlan


# =============================================================================
# DEFAULT CALLABLES
# =============================================================================
#
# IMPORTANT: these must be module-level, named functions - NOT lambdas.
#
# Django's migration writer has to be able to serialize whatever you pass
# as `default=` into a migration file, and it can only do that for named
# functions it can import by path. A `lambda: str(uuid.uuid4())` cannot
# be serialized (you'll hit "ValueError: Cannot serialize function:
# lambda" during `makemigrations`), whereas a plain named function like
# `generate_tx_ref` is written into the migration as
# `default=payments.models.generate_tx_ref` and works fine.
#
# Keep these here, not inline on the field, and pass the function itself
# (no parentheses) so Django calls it once per new row rather than
# evaluating it once at import time.


def generate_tx_ref():
    """
    A unique reference for one checkout attempt.

    Used as `tx_ref`'s default so every PaymentTransaction row is born
    with a reference we can hand to PayChangu, and later match back up
    when the callback/webhook comes in quoting the same ref.

    uuid4 is fine here: collisions are astronomically unlikely, and the
    field is also marked `unique=True` at the DB level, so a collision
    (however improbable) would fail loudly rather than silently
    overwriting anything. Not a secret - it's an identifier, not a
    token - so no need for `secrets` here.
    """
    return str(uuid.uuid4())


# =============================================================================
# PAYMENT TRANSACTION
# =============================================================================

class PaymentTransaction(models.Model):
    """
    One checkout attempt against a subscription plan.

    Lifecycle:

      1. subscriptions/views.py sends the user to a paid plan's upgrade
         button -> payments/services.start_subscription_checkout().
      2. That function creates one of these rows with status="pending"
         and tx_ref auto-generated below.
      3. The same function hands tx_ref to PayChangu and redirects the
         customer to PayChangu's hosted checkout page.
      4. When the customer comes back (callback_url) OR PayChangu tells
         us asynchronously (webhook), payments/services.verify_and_apply()
         looks this row up by tx_ref, re-verifies server-side with
         PayChangu, and - if the payment really succeeded - flips
         status to "success" and marks `applied` True.
      5. `applied` is the guard that makes step 4 idempotent: PayChangu
         retries webhooks on non-200 (3x over 90 minutes), and the
         callback and the webhook can both fire for the same payment.
         Without this flag, the subscription would get extended twice.

    Scoping note: this is tied directly to Subscription, not to a
    generic content-type link. That keeps the model honest about what
    it currently does. When customer/supplier payments arrive, widen
    this then - don't build the abstraction now and let it sit unused.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    # ------------------------------------------------------------------
    # Identity / gateway linkage
    # ------------------------------------------------------------------

    tx_ref = models.CharField(
        max_length=64,
        unique=True,
        default=generate_tx_ref,
        help_text=(
            "Our own reference for this checkout attempt - generated locally, "
            "sent to PayChangu on initiation, and echoed back in the redirect "
            "and webhook so we can find this row again."
        ),
    )

    # ------------------------------------------------------------------
    # What is being paid for
    # ------------------------------------------------------------------

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="payment_transactions",
        help_text="The subscription this payment will extend, if it succeeds.",
    )

    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="+",
        help_text=(
            "The plan the customer is buying. PROTECT (not CASCADE) so a "
            "plan can't be deleted out from under a historical transaction - "
            "deactivate plans instead of deleting them."
        ),
    )

    # ------------------------------------------------------------------
    # Money
    # ------------------------------------------------------------------

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Expected amount, in the currency below. Verified against PayChangu's response.",
    )

    currency = models.CharField(
        max_length=10,
        default="MWK",
        help_text="ISO currency code. Verified against PayChangu's response before applying.",
    )

    # ------------------------------------------------------------------
    # Provider + status
    # ------------------------------------------------------------------

    provider = models.CharField(
        max_length=20,
        default="paychangu",
        help_text=(
            "Which gateway handled this. Stored per-row so a future switch "
            "to Flutterwave/another adapter doesn't rewrite history."
        ),
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
    )

    applied = models.BooleanField(
        default=False,
        help_text=(
            "True once a successful transaction has actually extended the "
            "subscription. Separate from `status` because the callback and "
            "webhook can both fire, and PayChangu retries webhooks on "
            "non-200 - this guard makes applying the payment idempotent."
        ),
    )

    # ------------------------------------------------------------------
    # Debug / audit
    # ------------------------------------------------------------------

    raw_verification = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "The raw JSON response from PayChangu's verify endpoint. Kept "
            "so we can retroactively debug a disputed transaction without "
            "having to reproduce it against the live gateway."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tx_ref} ({self.status})"