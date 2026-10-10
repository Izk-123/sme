from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Invoice, Payment, Subscription, SubscriptionPlan


class PaymentInline(TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(ModelAdmin):
    list_display = ("name", "slug", "price_monthly", "max_users", "max_products", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Subscription)
class SubscriptionAdmin(ModelAdmin):
    list_display = ("organization", "plan", "status", "trial_end", "current_period_end", "grace_end")
    list_filter = ("status", "plan")
    search_fields = ("organization__name",)
    autocomplete_fields = ("organization", "plan")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Invoice)
class InvoiceAdmin(ModelAdmin):
    list_display = ("invoice_number", "subscription", "amount", "status", "period_start", "period_end")
    list_filter = ("status",)
    search_fields = ("invoice_number", "subscription__organization__name")
    inlines = [PaymentInline]


@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    list_display = ("invoice", "amount", "payment_method", "status", "created_at")
    list_filter = ("payment_method", "status")
    search_fields = ("invoice__invoice_number", "transaction_ref")
