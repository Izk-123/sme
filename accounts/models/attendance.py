from django.db import models
from django.utils import timezone


class AttendanceRecord(models.Model):
    """
    A daily attendance record for an employee. View-only from the
    self-service side for now (FR-05 asks employees to *view*
    attendance, not clock in/out themselves) - rows are created by an
    owner/admin, e.g. via /admin/.
    """

    STATUS_CHOICES = [
        ("present", "Present"),
        ("absent", "Absent"),
        ("late", "Late"),
        ("leave", "On Leave"),
    ]

    membership = models.ForeignKey(
        "accounts.Membership",
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    date = models.DateField(default=timezone.localdate)
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="present")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["membership", "date"], name="unique_attendance_per_day"),
        ]

    def __str__(self):
        return f"{self.membership.user.username} - {self.date} - {self.get_status_display()}"
