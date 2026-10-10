"""
payments/gateways/base.py

The abstraction the design discussion asked for:
`subscriptions -> payments.services -> gateway adapter -> PayChangu`.
Nothing outside this package should import paychangu.py directly -
callers ask payments.services for a checkout link or a verified
transaction, and get back plain dicts, not gateway-specific objects.

Scoped to Malawi mobile-money-first checkout for now (Standard/Hosted
Checkout - PayChangu's own hosted payment page). Direct mobile money
charging (no redirect) and a Flutterwave adapter are natural additions
later behind this same interface - not built now since only PayChangu
credentials exist.
"""
from abc import ABC, abstractmethod


class PaymentGateway(ABC):
    @abstractmethod
    def initiate_checkout(self, *, amount, currency, tx_ref, email, first_name, last_name,
                           callback_url, return_url, title, description, meta=None):
        """Returns {"checkout_url": str, "tx_ref": str, "raw": dict}."""
        raise NotImplementedError

    @abstractmethod
    def verify_transaction(self, tx_ref):
        """Returns {"status": "success"|"failed"|"pending", "amount": Decimal,
        "currency": str, "tx_ref": str, "raw": dict}."""
        raise NotImplementedError

    @abstractmethod
    def verify_webhook_signature(self, payload_bytes, signature_header):
        """Returns True/False. payload_bytes is the raw request body -
        HMAC verification breaks if you verify against re-serialized JSON
        instead of the exact bytes that were sent."""
        raise NotImplementedError
