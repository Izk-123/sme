# suppliers/admin.py
from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Supplier, SupplierPayment

@admin.register(Supplier)
class SupplierAdmin(ModelAdmin):
    list_display = ("name", "organization", "phone", "email", "outstanding_balance")
    list_filter = ("organization",)
    search_fields = ("name", "phone", "email")

@admin.register(SupplierPayment)
class SupplierPaymentAdmin(ModelAdmin):
    list_display = ("date", "supplier", "amount", "method", "reference", "organization")
    list_filter = ("organization", "method", "date")
    search_fields = ("supplier__name", "reference")
    list_select_related = ("supplier", "organization")

