from django.contrib import admin

try:
    from unfold.admin import ModelAdmin
except ImportError:  # Unfold not installed
    from django.contrib.admin import ModelAdmin

from .models import Expense, ExpenseCategory


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(ModelAdmin):
    list_display = ("name", "organization")
    list_filter = ("organization",)
    search_fields = ("name",)


@admin.register(Expense)
class ExpenseAdmin(ModelAdmin):
    list_display = ("date", "organization", "category", "amount", "supplier", "created_by")
    list_filter = ("organization", "category", "date", "supplier")
    search_fields = ("description", "supplier__name")
    list_select_related = ("category", "supplier", "organization")
