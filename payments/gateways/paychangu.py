"""
payments/gateways/paychangu.py

Built against developer.paychangu.com's documented Standard Checkout,
Transaction Verification, and Webhooks pages (fetched directly while
building this - not reconstructed from memory). Key things that came
straight from those docs and matter for correctness:

- Initiate: POST https://api.paychangu.com/payment, Bearer {secret_key}.
  Returns a checkout_url to redirect the customer to.
- Verify: GET https://api.paychangu.com/verify-payment/{tx_ref}. PayChangu's
  own docs are explicit: "before providing value to the customer, please
  make a server-side call to our transaction verification endpoint" -
  never trust a redirect query string or webhook payload on its own.
- Webhook signature: SHA-256 HMAC of the *raw* request body, using your
  webhook secret (not the API secret key - a different value from the
  same dashboard page), compared against the "Signature" request header.
- Which key you use (test vs live) determines test vs live mode - there's
  no separate "mode" flag to set.
"""
import hashlib
import hmac
import logging

import requests
from django.conf import settings

from .base import PaymentGateway

logger = logging.getLogger(__name__)

API_BASE = "https://api.paychangu.com"
REQUEST_TIMEOUT = 15  # seconds - don't let a slow gateway hang a web worker


class PayChanguGateway(PaymentGateway):
    def __init__(self, secret_key=None, webhook_secret=None):
        self.secret_key = secret_key or getattr(settings, "PAYCHANGU_SECRET_KEY", None)
        self.webhook_secret = webhook_secret or getattr(settings, "PAYCHANGU_WEBHOOK_SECRET", None)
        if not self.secret_key:
            raise ValueError("PAYCHANGU_SECRET_KEY is not set - see .env / settings.py")

    def _headers(self):
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.secret_key}",
        }

    def initiate_checkout(self, *, amount, currency, tx_ref, email, first_name, last_name,
                           callback_url, return_url, title, description, meta=None):
        payload = {
            # PayChangu's docs show amount as a plain number (int32) -
            # MWK has no meaningful fractional unit for this product, so
            # round rather than send a Decimal with a currency PayChangu
            # doesn't expect.
            "amount": int(amount),
            "currency": currency,
            "email": email or "",
            "first_name": first_name or "",
            "last_name": last_name or "",
            "callback_url": callback_url,
            "return_url": return_url,
            "tx_ref": tx_ref,
            "customization": {"title": title, "description": description},
            "meta": meta or {},
        }
        response = requests.post(
            f"{API_BASE}/payment", json=payload, headers=self._headers(), timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        checkout_url = data.get("data", {}).get("checkout_url")
        if not checkout_url:
            logger.error("PayChangu initiate_checkout returned no checkout_url: %s", data)
            raise RuntimeError("PayChangu didn't return a checkout URL - see logs.")

        return {"checkout_url": checkout_url, "tx_ref": tx_ref, "raw": data}

    def verify_transaction(self, tx_ref):
        response = requests.get(
            f"{API_BASE}/verify-payment/{tx_ref}", headers=self._headers(), timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
        data = body.get("data", {})

        return {
            "status": data.get("status", "failed"),
            "amount": data.get("amount"),
            "currency": data.get("currency"),
            "tx_ref": data.get("tx_ref", tx_ref),
            "raw": body,
        }

    def verify_webhook_signature(self, payload_bytes, signature_header):
        if not self.webhook_secret:
            logger.error("PAYCHANGU_WEBHOOK_SECRET is not set - refusing to trust unverifiable webhook")
            return False
        if not signature_header:
            return False

        computed = hmac.new(
            self.webhook_secret.encode("utf-8"), payload_bytes, hashlib.sha256
        ).hexdigest()
        # constant-time compare - a naive `==` leaks timing information
        # that can be used to guess the correct signature byte-by-byte.
        return hmac.compare_digest(computed, signature_header)
