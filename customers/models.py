"""
Customers and payments.

Balance model
-------------
A customer's outstanding balance is:

    opening_balance + sum(credit sales) - sum(payments received)

`opening_balance` holds what they owed before they started using ChumaFlow
(typed in from the paper ledger). Storing it separately means recalculating
the balance from sales and payments can never wipe it out — which was the
bug in the previous version, where the balance was the *only* place an
opening figure could live, and `update_balance()` overwrote it.

`outstanding_balance` is a cached copy of that calculation, kept so list
pages don't have to aggregate on every row. Never edit it by hand or with
`-=` inside a view; always call `update_balance()`.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from organizations.models import Organization


class Customer(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="customers"
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    location = models.CharField(max_length=200, blank=True)

    opening_balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="What this customer owed before they were added to ChumaFlow.",
    )
    outstanding_balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Derived: opening balance + credit sales - payments. Do not edit by hand.",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Deactivate instead of deleting, so historical sales and payments keep their link.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def calculate_balance(self):
        """
        Return the balance without saving it.

        Prefer this to reading `outstanding_balance` when correctness
        matters more than speed (e.g. checking an overpayment). Read the
        cached field for list pages, where an extra aggregate per row
        would be wasteful.
        """
        credit = self.sales.filter(payment_method="credit").aggregate(
            total=models.Sum("total")
        )["total"] or Decimal("0")

        paid = self.payments.aggregate(
            total=models.Sum("amount")
        )["total"] or Decimal("0")

        return self.opening_balance + credit - paid

    def update_balance(self):
        """
        Recalculate and persist the cached balance.

        Call this inside the same transaction as any credit sale or
        payment, after the row that changed has been written.
        """
        self.outstanding_balance = self.calculate_balance()
        self.save(update_fields=["outstanding_balance"])


class Payment(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("airtel_money", "Airtel Money"),
        ("tnm_mpamba", "TNM Mpamba"),
        ("bank", "Bank Transfer"),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="payments"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="payments"
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        # A zero or negative payment would either do nothing or *increase*
        # the debt. The form enforces the same floor; this is the belt.
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHODS, default="cash"
    )
    reference = models.CharField(
        max_length=100, blank=True,
        help_text="Optional reference, e.g. invoice or transaction ID.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.customer.name} - MK{self.amount} ({self.payment_method})"