# sales/models.py
import uuid
from django.db import models
from django.utils.html import format_html
from organizations.models import Organization
from customers.models import Customer

class Product(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="products")
    sku = models.CharField(max_length=50, blank=True, null=True, unique=True, help_text="Stock Keeping Unit")
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True, help_text="Product category")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    stock_quantity = models.IntegerField(default=0)
    barcode = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="EAN-13, UPC, or internal barcode",
    )
    low_stock_threshold = models.PositiveIntegerField(default=5, help_text="Alert when stock falls below this number")

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.low_stock_threshold

    @property
    def stock_value(self):
        return self.price * self.stock_quantity

    def save(self, *args, **kwargs):
        # Auto‑generate SKU if blank
        if not self.sku:
            self.sku = uuid.uuid4().hex[:8].upper()
        # Auto‑generate barcode if blank
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

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="stock_movements")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_movements")
    quantity = models.IntegerField()  # positive = in, negative = out
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    reference = models.CharField(max_length=100, blank=True)  # e.g., "Sale #12" or "PO #5"
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements"
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

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="sales")
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default="cash")
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

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

    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"
