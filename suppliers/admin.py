# suppliers/admin.py
from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Supplier

@admin.register(Supplier)
class SupplierAdmin(ModelAdmin):
    list_display = ("name", "organization", "phone", "email", "outstanding_balance")
    list_filter = ("organization",)
    search_fields = ("name", "phone", "email")