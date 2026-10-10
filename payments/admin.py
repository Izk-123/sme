from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import PaymentTransaction


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(ModelAdmin):
    list_display = ("tx_ref", "subscription", "plan", "amount", "currency", "status", "applied", "created_at")
    list_filter = ("status", "applied", "provider")
    search_fields = ("tx_ref", "subscription__organization__name")
    readonly_fields = ("tx_ref", "raw_verification", "created_at", "updated_at")
