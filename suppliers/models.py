"""
Supplier and SupplierPayment models.

Money rules this module enforces
--------------------------------
A supplier's outstanding balance is derived, never entered by hand. It is:

    opening_balance
  + sum of deliveries       (each at the cost recorded on that delivery)
  + sum of unpaid expenses  (Expense.on_credit = True)
  − sum of payments

Three invariants that make the number trustworthy:

  1. Each delivery's cost is frozen on the StockMovement row
     (StockMovement.unit_cost). Later changes to the product's own
     average cost do NOT retroactively revalue an old delivery — the
     supplier was owed what was agreed at the time.

  2. Only expenses marked on_credit=True count. Paying a supplier in
     cash must not increase what you owe them.

  3. opening_balance captures any balance carried over from before
     ChumaFlow was in use, so a "migrated" supplier reconciles.

update_balance() is idempotent and safe to re-run — the
`recompute_supplier_balances` management command exists precisely
because the signals are best-effort (a failed recompute is logged, not
re-raised, so it can't roll back the triggering write). Recompute is
the repair path.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    Sum,
)
from django.db.models.functions import Coalesce

from organizations.models import Organization


class Supplier(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="suppliers",
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    # Cached total — always recomputed by update_balance(). Do nots
    # write to it directly anywhere except inside update_balance();
    # otherwise the reports, the cash page and this page will disagree.
    outstanding_balance = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
    )

    # What you owed this supplier before you started using ChumaFlow.
    # Counted once, added to the rolling total, and never touched by
    # later deliveries, expenses or payments.
    opening_balance = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=Decimal("0.00"),
        help_text="What you already owed this supplier before using ChumaFlow.",
    )

    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Inactive suppliers are hidden from pickers and the default "
            "list view, but their history and balance are preserved."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            # The list view and the payables report both filter by
            # organisation and (usually) is_active. One composite
            # index covers both.
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self):
        return self.name

    def update_balance(self):
        """
        Recompute `outstanding_balance` from history.

        Wrapped in a transaction with select_for_update() so two
        concurrent signal fires (e.g. recording two payments at once)
        cannot interleave their reads and writes. On SQLite the lock
        is a no-op; on PostgreSQL it is a real row lock.

        The write is skipped when nothing changed, so bulk imports
        don't fan out into hundreds of no-op UPDATEs.
        """
        with transaction.atomic():
            supplier = Supplier.objects.select_for_update().get(pk=self.pk)

            # Cost of one unit on a delivery: prefer the cost recorded
            # on the movement itself. Old rows with no unit_cost fall
            # back to the product's current cost — the data migration
            # in `0005_freeze_purchase_costs` freezes them once, after
            # which they no longer drift.
            line_cost = Coalesce(
                F("unit_cost"),
                F("product__cost_price"),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
            purchase_total = (
                supplier.stock_movements
                .filter(movement_type="purchase")
                .aggregate(
                    t=Sum(
                        ExpressionWrapper(
                            F("quantity") * line_cost,
                            output_field=DecimalField(max_digits=14, decimal_places=2),
                        )
                    )
                )["t"]
                or Decimal("0.00")
            )

            # Only expenses you haven't paid yet count as owed.
            expense_total = (
                supplier.expenses
                .filter(on_credit=True)
                .aggregate(t=Sum("amount"))["t"]
                or Decimal("0.00")
            )

            payment_total = (
                supplier.payments
                .aggregate(t=Sum("amount"))["t"]
                or Decimal("0.00")
            )

            new_balance = (
                supplier.opening_balance
                + purchase_total
                + expense_total
                - payment_total
            )

            if supplier.outstanding_balance != new_balance:
                supplier.outstanding_balance = new_balance
                supplier.save(update_fields=["outstanding_balance", "updated_at"])

            # Keep the in-memory instance consistent with the persisted
            # value so callers reading `self.outstanding_balance` right
            # after update_balance() see the fresh number.
            self.outstanding_balance = new_balance


class SupplierPayment(models.Model):
    """A payment made to a supplier. Reduces what we owe."""

    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("airtel_money", "Airtel Money"),
        ("tnm_mpamba", "TNM Mpamba"),
        ("bank", "Bank Transfer"),
        ("other", "Other"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="supplier_payments",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    date = models.DateField()
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    method = models.CharField(
        max_length=20, choices=PAYMENT_METHODS, default="cash",
    )
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.date} -> {self.supplier.name} MK{self.amount}"