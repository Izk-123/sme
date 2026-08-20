# expenses/admin.py
from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Expense, ExpenseCategory

@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(ModelAdmin):
    list_display = ("name", "organization")
    list_filter = ("organization",)

@admin.register(Expense)
class ExpenseAdmin(ModelAdmin):
    list_display = ("date", "organization", "category", "amount", "supplier", "created_by")
    list_filter = ("organization", "category", "date")
    search_fields = ("description", "supplier")