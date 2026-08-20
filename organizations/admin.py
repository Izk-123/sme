from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(ModelAdmin):
    list_display = ("name", "business_type", "currency", "created_at")
    list_filter = ("business_type",)
    search_fields = ("name",)
