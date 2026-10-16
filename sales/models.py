"""
Sales, products and stock movements.

Multi-tenancy notes
-------------------
Everything here belongs to an Organization. Two constraints in particular
matter:

  * Product.sku is unique per organization, not globally. A global unique
    would let one shop "claim" a common SKU like "RICE-5KG" and block
    every other shop from using it — and the resulting error would leak
    the fact that the SKU exists at another business.

  * SaleItem.unit_cost snapshots the product's cost at the moment of sale,
    so historical profit figures don't change when a product's cost is
    later updated by a stock receipt.
"""
import uuid

from django.conf import settings
from django.db import models

from customers.models import Customer
from organizations.models import Organization


class Product(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="products"
    )
    sku = models.CharField(
        max_length=50, blank=True, null=True,
        help_text="Stock Keeping Unit. Unique within your business.",
    )
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)

    cost_price = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        help_text="What this product costs us to buy.",
    )
    stock_quantity = models.IntegerField(default=0)
    barcode = models.CharField(
        max_length=100, blank=True, db_index=True,
        help_text="Internal barcode. Not a real EAN-13 — see utils.generate_barcode.",
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=5, help_text="Alert when stock falls below this number."
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "sku"],
                name="uniq_sku_per_org",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.low_stock_threshold

    @property
    def stock_value(self):
        """Retail value of stock on hand. See StockValuationView for the cost version."""
        return self.price * self.stock_quantity

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
        Organization, on_delete=models.CASCADE, related_name="stock_movements"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="stock_movements"
    )
    quantity = models.IntegerField()  # positive = in, negative = out
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    reference = models.CharField(max_length=100, blank=True)
    supplier = models.ForeignKey(
        "suppliers.Supplier", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="stock_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} {self.quantity} ({self.movement_type})"


class Sale(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("airtel_money", "Airtel Money"),
        ("tnm_mpamba", "TNM Mpamba"),
        ("bank", "Bank Transfer"),
        ("credit", "Credit"),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="sales"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sales",
    )
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHODS, default="cash"
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

    def __str__(self):
        return f"Sale #{self.pk} - {self.total}"


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    # Cost at the moment of sale. Nullable so existing rows don't break the
    # migration; new rows always set it from product.cost_price.
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Product cost at the time of sale. Historical profit uses this, not the current cost.",
    )

    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"