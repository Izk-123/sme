"""
Admin registration.

Suppliers are never deleted from the app — that would cascade through
StockMovement.supplier and Expense.supplier (both SET_NULL) and silently
erase every historical debt. Deactivation is the only supported path.
Below we remove the admin's delete action and delete button to enforce
that even from the admin.
"""
from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Supplier, SupplierPayment


@admin.register(Supplier)
class SupplierAdmin(ModelAdmin):
    list_display = (
        "name", "organization", "phone", "email",
        "outstanding_balance", "opening_balance", "is_active",
    )
    list_filter = ("organization", "is_active")
    search_fields = ("name", "phone", "email")
    # Recompute-after-manual-edit is handled by the signals; nothing
    # else is exposed for editing here on purpose.
    readonly_fields = ("outstanding_balance",)

    def has_delete_permission(self, request, obj=None):
        # Block hard deletes: use the is_active flag instead.
        return False


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(ModelAdmin):
    list_display = (
        "date", "supplier", "amount", "method", "reference", "organization",
    )
    list_filter = ("organization", "method", "date")
    search_fields = ("supplier__name", "reference")
    list_select_related = ("supplier", "organization")