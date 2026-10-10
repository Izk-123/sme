from django.conf import settings
from django.db import models


class ExpenseRequest(models.Model):
    """
    An expense claim an employee submits for owner approval - distinct
    from expenses.models.Expense (an already-recorded business expense).
    Approving one of these doesn't itself create an Expense record yet -
    that's a manual step for the owner for now (see
    accounts.views.TeamRequestsView), same "manual until there's a
    second real use case" scoping applied elsewhere in this project.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    membership = models.ForeignKey(
        "accounts.Membership",
        on_delete=models.CASCADE,
        related_name="expense_requests",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    category = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    receipt = models.ImageField(upload_to="expense_receipts/", null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_expense_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.membership.user.username} - {self.amount}"
