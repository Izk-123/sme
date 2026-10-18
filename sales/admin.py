from django.contrib import admin
from django.utils.html import format_html

from unfold.admin import ModelAdmin, TabularInline

from .models import Product, Sale, SaleItem, StockMovement


class SaleItemInline(TabularInline):
    model = SaleItem
    extra = 1


@admin.register(Sale)
class SaleAdmin(ModelAdmin):
    list_display = (
        "id", "organization", "customer", "payment_method",
        "total", "amount_paid", "status_display", "due_date",
        "created_by", "created_at",
    )
    list_filter = (
        "payment_method", "organization", "due_date", "created_at",
    )
    search_fields = ("id", "customer__name", "created_by__username")
    inlines = [SaleItemInline]
    readonly_fields = ("submission_token",)

    @admin.display(description="Status")
    def status_display(self, obj):
        labels = {
            "paid":    ("Paid",    "green"),
            "partial": ("Partial", "orange"),
            "unpaid":  ("Unpaid",  "red"),
        }
        label, colour = labels.get(obj.status, (obj.status, "gray"))
        return format_html(
            '<span style="color:{};font-weight:bold;">{}</span>',
            colour, label,
        )


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = (
        "name", "organization", "price", "cost_price",
        "stock_quantity", "low_stock_threshold", "stock_status",
    )
    list_filter = ("organization",)
    search_fields = ("name", "sku", "barcode")
    fields = (
        "name", "organization", "sku", "category", "price", "cost_price",
        "stock_quantity", "low_stock_threshold", "barcode",
    )

    @admin.display(description="Stock Status")
    def stock_status(self, obj):
        if obj.is_low_stock:
            return format_html('<span style="color:red;font-weight:bold;">Low Stock</span>')
        return "OK"


@admin.register(StockMovement)
class StockMovementAdmin(ModelAdmin):
    list_display = (
        "product", "quantity", "unit_cost", "movement_type",
        "supplier", "reference", "created_at",
    )
    list_filter = ("movement_type", "organization", "product", "supplier")
    search_fields = ("product__name", "reference")
    readonly_fields = ("created_at",)