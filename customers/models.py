"""
Customers, payments and payment allocations.

Balance model
-------------
A customer's outstanding balance is:

    opening_balance
  + sum(sale.total - sale.amount_paid)   # unpaid from each sale
  - sum(payments.amount)                 # everything they've handed over

The old version filtered `sales` by `payment_method=='credit'`. That
worked while a sale was either fully cash or fully credit, but breaks
the moment a sale is part-paid: `payment_method` records the method
used for the PAID portion, while `amount_paid` records how much was
handed over. So `total - amount_paid` is what's actually owed, and
summing that across every sale is correct regardless of the method.

PaymentAllocation links a specific Payment to a specific Sale, used by
the debt-ageing report so we can say which sale is still open. It does
not participate in `calculate_balance()` — the balance is derived from
payments directly (so overpayments count immediately as credit, even
when there's no sale to allocate to). Allocations can therefore be
absent without changing the balance.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import DecimalField, ExpressionWrapper, F, Sum

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
        help_text="Derived: opening balance + unpaid-from-sales - payments. Do not edit by hand.",
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
        Return the live balance without saving.

        Reads `total - amount_paid` on each sale, so it stays correct
        for partial-credit sales as well as full credit/cash. Payments
        are subtracted regardless of allocations — a prepayment counts
        even when there's no sale to allocate it to.
        """
        unpaid_from_sales = (
            self.sales
            .annotate(
                unpaid=ExpressionWrapper(
                    F("total") - F("amount_paid"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
            .aggregate(t=Sum("unpaid"))["t"]
            or Decimal("0")
        )
        paid = (
            self.payments.aggregate(t=Sum("amount"))["t"]
            or Decimal("0")
        )
        return self.opening_balance + unpaid_from_sales - paid

    def update_balance(self):
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


class PaymentAllocation(models.Model):
    """
    Which sale(s) a payment settled.

    Populated FIFO at the moment the payment is saved (see
    customers/services.py::allocate_payment). Used by the debt-ageing
    report so a customer with three open sales shows each sale in its
    own bucket rather than one lumped sum.
    """
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="payment_allocations",
    )
    payment = models.ForeignKey(
        Payment, on_delete=models.CASCADE, related_name="allocations",
    )
    sale = models.ForeignKey(
        "sales.Sale", on_delete=models.CASCADE, related_name="payment_allocations",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # One allocation per (payment, sale) pair. A second payment
        # against the same sale creates a new row with its own amount;
        # a second allocation of the SAME payment to the SAME sale
        # would be an error.
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "sale"],
                name="uniq_payment_sale_allocation",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.payment_id} -> Sale #{self.sale_id}: MK{self.amount}"