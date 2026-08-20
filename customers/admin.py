# customers/admin.py
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from .models import Customer, Payment

class PaymentInline(TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("created_at", "created_by")

@admin.register(Customer)
class CustomerAdmin(ModelAdmin):
    list_display = ("name", "organization", "phone", "outstanding_balance")
    list_filter = ("organization",)
    search_fields = ("name", "phone")
    inlines = [PaymentInline]

@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    list_display = ("customer", "amount", "payment_method", "created_at", "created_by")
    list_filter = ("payment_method", "organization", "created_at")
    search_fields = ("customer__name", "reference")