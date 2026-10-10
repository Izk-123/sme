from django.conf import settings
from django.db import models


class EmployeeRequest(models.Model):
    """
    A generic employee request (leave, equipment, other) awaiting owner
    review. Named EmployeeRequest rather than the more generic "Request"
    to avoid reading confusingly close to Django's own HttpRequest.
    """

    REQUEST_TYPES = [
        ("leave", "Leave"),
        ("equipment", "Equipment"),
        ("other", "Other"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    membership = models.ForeignKey(
        "accounts.Membership",
        on_delete=models.CASCADE,
        related_name="requests",
    )
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPES)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_employee_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.membership.user.username} - {self.get_request_type_display()}"
