"""
Expense and ExpenseCategory models.

Money rules this module enforces
--------------------------------
  * Every Expense reduces profit (it always counts, whether paid or
    not — that's accrual accounting).
  * Only Expenses with `on_credit=True` increase what you owe a
    supplier. A cash-paid delivery fee does NOT create a debt.
  * `payment_method` records how the money actually left the business
    (cash, mobile money, bank). This is what the Cash Report uses to
    compute "money out". It must be empty when `on_credit=True` —
    you haven't paid anything yet.

Stock you buy to resell is NOT an expense here. That flow lives in
the sales app (Receive Stock), where it becomes cost-of-goods when
the stock is sold. The form blocks stock-ish category names to make
the double-count mistake harder.
"""
from django.conf import settings
from django.db import models

from organizations.models import Organization


class ExpenseCategory(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="expense_categories",
    )
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Expense(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("airtel_money", "Airtel Money"),
        ("tnm_mpamba", "TNM Mpamba"),
        ("bank", "Bank Transfer"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    date = models.DateField()
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name="expenses",
    )
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="expenses",
        help_text="Optional. Link this expense to a supplier if it came from one.",
    )

    # The two fields that make supplier balances and the cash report
    # honest. Before these existed, every supplier-linked expense
    # counted as owed even when it had been paid in cash, and there
    # was no way to know whether money actually left the business.
    on_credit = models.BooleanField(
        default=False,
        help_text=(
            "Tick if you have NOT paid this supplier yet. Only unpaid "
            "expenses count as owed."
        ),
    )
    payment_method = models.CharField(
        max_length=20,
        blank=True,
        choices=PAYMENT_METHODS,
        help_text=(
            "How it was paid. Needed for a real cash report. "
            "Leave blank if 'on credit' is ticked."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
    )

    def __str__(self):
        return f"{self.date} - {self.category} - MK{self.amount}"