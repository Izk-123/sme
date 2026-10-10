# expenses/models.py
from django.db import models
from django.conf import settings
from organizations.models import Organization

class ExpenseCategory(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="expense_categories")
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class Expense(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="expenses")
    date = models.DateField()
    category = models.ForeignKey(ExpenseCategory, on_delete=models.SET_NULL, null=True, related_name="expenses")
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses",
        help_text="Optional. Link this expense to a supplier if it came from one.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"{self.date} - {self.category} - MK{self.amount}"