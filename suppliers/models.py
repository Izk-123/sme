# suppliers/models.py

from django.conf import settings
from django.db.models.functions import Coalesce

from django.db.models import Sum, F, DecimalField, ExpressionWrapper

from decimal import Decimal

from django.db import models

from organizations.models import Organization



class Supplier(models.Model):

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="suppliers")

    name = models.CharField(max_length=200)

    phone = models.CharField(max_length=20, blank=True)

    email = models.EmailField(blank=True)

    address = models.TextField(blank=True)

    outstanding_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)



    def __str__(self):

        return self.name


    def update_balance(self):
        """
        Recompute outstanding_balance from history. Self-healing: call
        this any time and it corrects drift.

          owed = Σ(purchase qty × cost_price)
               + Σ(expenses linked to this supplier)
               − Σ(payments made to this supplier)
        """
        # Purchases: qty × cost_price (fall back to selling price)
        unit_cost = Coalesce(
            F("product__cost_price"),
            F("product__price"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
        purchase_total = (
            self.stock_movements
            .filter(movement_type="purchase")
            .aggregate(
                total=Sum(
                    ExpressionWrapper(
                        F("quantity") * unit_cost,
                        output_field=DecimalField(max_digits=14, decimal_places=2),
                    )
                )
            )["total"]
            or Decimal("0.00")
        )

        # Expenses billed by this supplier
        expense_total = (
            self.expenses.aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        # Payments we've made to this supplier
        payment_total = (
            self.payments.aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        self.outstanding_balance = purchase_total + expense_total - payment_total
        self.save(update_fields=["outstanding_balance"])

class SupplierPayment(models.Model):
    """A payment made to a supplier — reduces what we owe."""

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
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(
        max_length=20, choices=PAYMENT_METHODS, default="cash"
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

