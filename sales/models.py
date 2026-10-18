"""
Sales, products and stock movements.

Money rules this module encodes
-------------------------------
  * `SaleItem.unit_cost` — the cost of one unit at the moment of sale.
    Reports use COALESCE(unit_cost, product.cost_price) so historical
    profit is frozen once the sale happens.

  * `StockMovement.unit_cost` — the cost of one unit on a DELIVERY.
    This is what Supplier.update_balance() reads; kept separate from
    SaleItem.unit_cost because the same product can be bought and sold
    at different costs on different days.

  * `Sale.amount_paid` — how much cash/mobile-money the customer handed
    over AT THE TIME OF SALE. Authoritative for "is this sale paid?".
    The unpaid part is `total - amount_paid`. Never trust
    payment_method=='credit' to mean anything: with amount_paid, a
    partial cash sale has payment_method=='cash' and amount_paid > 0.

  * `Sale.due_date` — optional date the unpaid portion is due.
    Ageing falls back to created_at + 30 days when not set.

  * `Sale.submission_token` — a per-form UUID. Uniqueness stops a
    double-tapped "Complete sale" from saving twice.

Multi-tenancy notes
-------------------
Product.sku is unique per organization, not globally.
"""
import uuid

from django.conf import settings
from django.db import models

from customers.models import Customer
from organizations.models import Organization


class Product(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="products",
    )
    sku = models.CharField(
        max_length=50, blank=True, null=True,
        help_text="Stock Keeping Unit. Unique within your business.",
    )
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)

    cost_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="What this product costs us to buy.",
    )
    stock_quantity = models.IntegerField(default=0)
    barcode = models.CharField(
        max_length=100, blank=True, db_index=True,
        help_text="Internal barcode. Not a real EAN-13 — see utils.generate_barcode.",
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=5, help_text="Alert when stock falls below this number.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "sku"], name="uniq_sku_per_org",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.low_stock_threshold

    @property
    def retail_value(self):
        return self.price * self.stock_quantity

    @property
    def cost_value(self):
        if self.cost_price is None:
            return None
        return self.cost_price * self.stock_quantity

    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = uuid.uuid4().hex[:8].upper()
        if not self.barcode:
            from .utils import generate_barcode
            self.barcode = generate_barcode()
        super().save(*args, **kwargs)


class StockMovement(models.Model):
    MOVEMENT_TYPES = [
        ("purchase", "Purchase"),
        ("sale", "Sale"),
        ("adjustment", "Adjustment"),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="stock_movements",
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="stock_movements",
    )
    quantity = models.IntegerField()
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    reference = models.CharField(max_length=100, blank=True)
    supplier = models.ForeignKey(
        "suppliers.Supplier", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="stock_movements",
    )
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="What was paid per unit on this delivery.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} {self.quantity} ({self.movement_type})"

    @property
    def line_total(self):
        cost = self.unit_cost
        if cost is None:
            cost = getattr(self.product, "cost_price", None)
        if cost is None:
            return None
        return self.quantity * cost


class Sale(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("airtel_money", "Airtel Money"),
        ("tnm_mpamba", "TNM Mpamba"),
        ("bank", "Bank Transfer"),
        ("credit", "Credit"),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="sales",
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sales",
    )

    # The method used for the PAID portion. When amount_paid == 0 this
    # is 'credit'; when amount_paid > 0 it names a real method (cash,
    # airtel_money, …). Reports read `amount_paid`, not this field.
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHODS, default="cash",
    )

    # What the customer paid AT THE TIME OF SALE. The unpaid part is
    # `total - amount_paid`; Customer.calculate_balance() sums it across
    # all a customer's sales.
    amount_paid = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Cash or mobile money received at the time of sale.",
    )

    # Optional due date for the unpaid portion. Ageing falls back to
    # created_at + 30 days when this is null.
    due_date = models.DateField(
        null=True, blank=True,
        help_text="When the unpaid portion is due. Optional.",
    )

    # Idempotency token: one per sale form render. A second POST with
    # the same token is refused by the unique constraint, so a slow
    # connection and a double-tap can't create two sales.
    submission_token = models.CharField(
        max_length=64, blank=True, null=True, unique=True,
        help_text="Internal idempotency token for the sale form.",
    )

    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sales_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def recalculate_total(self):
        self.total = sum(item.subtotal() for item in self.items.all())
        self.save(update_fields=["total"])

    @property
    def outstanding(self):
        """How much of this sale is still owed."""
        return self.total - self.amount_paid

    @property
    def status(self):
        """'paid' | 'partial' | 'unpaid' — the label the templates show."""
        if self.amount_paid >= self.total:
            return "paid"
        if self.amount_paid > 0:
            return "partial"
        return "unpaid"

    def __str__(self):
        return f"Sale #{self.pk} - {self.total}"


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text=(
            "Product cost at the time of sale. Historical profit uses "
            "this, not the current cost."
        ),
    )

    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"