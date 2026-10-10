import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from core.permissions import OrganizationMixin, RoleRequiredMixin
from subscriptions.models import SubscriptionPlan
from subscriptions.services import get_subscription

from .models import PaymentTransaction
from .services import get_gateway, start_subscription_checkout, verify_and_apply

logger = logging.getLogger(__name__)


class InitiateSubscriptionCheckoutView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    """POST target from the Upgrade page's plan buttons for any paid
    plan - the Free plan still switches instantly with no payment
    (see subscriptions/views.py's UpgradePlanView, which handles that
    case before ever reaching here)."""

    allowed_roles = ["owner"]

    def get(self, request):
        return self._start(request, request.GET.get("plan"))

    def post(self, request):
        return self._start(request, request.POST.get("plan"))

    def _start(self, request, plan_id):
        organization = self.get_organization()
        plan = get_object_or_404(SubscriptionPlan, pk=plan_id, is_active=True)
        subscription = get_subscription(organization)

        try:
            checkout_url = start_subscription_checkout(request, subscription, plan)
        except Exception:
            logger.exception("Failed to start PayChangu checkout for org %s", organization.pk)
            messages.error(request, "Couldn't start checkout right now - please try again shortly.")
            return redirect("upgrade_plan")

        return redirect(checkout_url)


class PaymentCallbackView(View):
    """
    PayChangu's callback_url - where the customer's browser lands after
    completing (or attempting) payment on PayChangu's hosted page.
    Per PayChangu's own docs, this is a redirect, not proof of anything -
    always re-verify server-side before treating the payment as real,
    which is exactly what verify_and_apply() does.
    """

    def get(self, request):
        tx_ref = request.GET.get("tx_ref")
        if not tx_ref:
            return HttpResponseBadRequest("Missing tx_ref")

        transaction = verify_and_apply(tx_ref)
        if transaction is None:
            messages.error(request, "We couldn't find that payment.")
        elif transaction.status == "success":
            messages.success(request, f"Payment received - you're now on the {transaction.plan.name} plan.")
        else:
            messages.error(request, "That payment didn't go through. You can try again.")

        return redirect("subscription_detail")


class PaymentReturnView(View):
    """PayChangu's return_url - reached when the customer cancels or
    exhausts failed attempts on the hosted checkout page. No charge to
    verify here; just send them back with a clear message."""

    def get(self, request):
        messages.info(request, "Checkout was cancelled - no payment was made.")
        return redirect("upgrade_plan")


@method_decorator(csrf_exempt, name="dispatch")
class PayChanguWebhookView(View):
    """
    Public, CSRF-exempt (PayChangu can't send a Django CSRF token) -
    safe because every request is verified against the HMAC "Signature"
    header before anything happens. Always returns 200 once the
    signature check passes, even if verify_and_apply() finds nothing to
    do, per PayChangu's docs: any non-200 triggers 3 retries over 90
    minutes, so a 4xx/5xx here should mean "genuinely couldn't process
    this," not "still thinking about it."
    """

    def post(self, request):
        signature = request.headers.get("Signature")
        gateway = get_gateway()

        if not gateway.verify_webhook_signature(request.body, signature):
            logger.warning("Rejected PayChangu webhook with invalid signature")
            return HttpResponse(status=400)

        import json
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            payload = {}

        # PayChangu's docs confirm tx_ref appears in webhook payloads
        # "for any transaction" but the only full example shown is for a
        # Direct API charge (a different product than Standard Checkout,
        # which is what start_subscription_checkout uses), and that
        # example uses "reference" rather than "tx_ref". Checking both,
        # and logging the full payload on first receipt, so you can
        # confirm the exact field name from a real test webhook rather
        # than trusting this comment.
        tx_ref = payload.get("tx_ref") or payload.get("reference")
        logger.info("PayChangu webhook received: %s", payload)

        if tx_ref:
            verify_and_apply(tx_ref)
        else:
            logger.warning("PayChangu webhook had a valid signature but no tx_ref/reference: %s", payload)

        return HttpResponse(status=200)
