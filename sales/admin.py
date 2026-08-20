# sales/admin.py
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from .models import Product, Sale, SaleItem, StockMovement

class SaleItemInline(TabularInline):
    model = SaleItem
    extra = 1

@admin.register(Sale)
class SaleAdmin(ModelAdmin):
    list_display = ("id", "organization", "customer", "payment_method", "total", "created_at")
    list_filter = ("payment_method", "organization")
    inlines = [SaleItemInline]

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ("name", "organization", "price", "stock_quantity", "low_stock_threshold", "stock_status")
    list_filter = ("organization",)
    search_fields = ("name",)
    fields = ("name", "organization", "price", "stock_quantity", "low_stock_threshold")

    def stock_status(self, obj):
        if obj.is_low_stock:
            return format_html('<span style="color: red; font-weight: bold;">⚠️ Low Stock</span>')
        return "OK"
    stock_status.short_description = "Stock Status"

@admin.register(StockMovement)
class StockMovementAdmin(ModelAdmin):
    list_display = ("product", "quantity", "movement_type", "reference", "created_at")
    list_filter = ("movement_type", "organization", "product")
    search_fields = ("product__name", "reference")
    readonly_fields = ("created_at",)