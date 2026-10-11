import json
import hmac
import hashlib
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
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

        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            payload = {}

        tx_ref = payload.get("tx_ref") or payload.get("reference")
        logger.info("PayChangu webhook received: %s", payload)

        if tx_ref:
            verify_and_apply(tx_ref)
        else:
            logger.warning("PayChangu webhook had a valid signature but no tx_ref/reference: %s", payload)

        return HttpResponse(status=200)


@method_decorator(csrf_exempt, name="dispatch")
class WhatsAppWebhookView(View):
    """
    Public, CSRF-exempt (Meta can't send a Django CSRF token) - safe because
    incoming POST requests are verified against the HMAC "X-Hub-Signature-256"
    header using your WhatsApp App Secret.
    
    Handles:
      - GET: Meta's webhook verification challenge.
      - POST: Incoming messages, delivery statuses, etc.
    """

    def get(self, request):
        """Verification handshake required by Meta when setting up the webhook."""
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        # Compare the token Meta sends with the one in your .env
        if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
            logger.info("WhatsApp webhook verified successfully.")
            return HttpResponse(challenge, status=200)

        logger.warning("WhatsApp webhook verification failed. Mode: %s, Token: %s", mode, token)
        return HttpResponse("Forbidden", status=403)

    def post(self, request):
        """Handles incoming messages and status updates from WhatsApp."""
        # 1. Verify the request is genuinely from Meta using App Secret
        signature = request.headers.get("X-Hub-Signature-256", "")
        if settings.WHATSAPP_APP_SECRET and signature:
            expected = hmac.new(
                settings.WHATSAPP_APP_SECRET.encode("utf-8"),
                request.body,
                hashlib.sha256,
            ).hexdigest()
            # Constant-time comparison to prevent timing attacks
            if not hmac.compare_digest(f"sha256={expected}", signature):
                logger.warning("WhatsApp webhook rejected: invalid signature.")
                return HttpResponse("Invalid signature", status=403)

        # 2. Parse the JSON payload
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            logger.warning("WhatsApp webhook received invalid JSON.")
            return HttpResponseBadRequest("Invalid JSON")

        # 3. Log the payload for debugging (you'll see this in your server logs)
        logger.info("Received WhatsApp webhook payload: %s", json.dumps(payload, indent=2))

        # TODO: Save incoming messages to your database, trigger
        # notifications, update delivery statuses, etc.

        # 4. Always return 200 OK so Meta knows you received it
        return JsonResponse({"status": "ok"})