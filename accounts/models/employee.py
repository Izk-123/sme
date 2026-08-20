from django.db import models


class EmployeeProfile(models.Model):
    """
    Business-specific employment details. Tied to a Membership (this
    person, at this business), NOT to User directly - salary, job title,
    and department belong to the employment relationship, not the
    person. The same user can have a different EmployeeProfile at each
    business they're a member of.

    Intentionally shallow - this is identity/RBAC scaffolding, not an
    HRMS. No recruitment, appraisal, payroll, or leave management here;
    add those as separate apps later if the product actually needs them.
    """

    EMPLOYMENT_TYPES = [
        ("full_time", "Full-time"),
        ("part_time", "Part-time"),
        ("casual", "Casual"),
        ("contract", "Contract"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("on_leave", "On Leave"),
        ("terminated", "Terminated"),
    ]

    membership = models.OneToOneField(
        "accounts.Membership",
        on_delete=models.CASCADE,
        related_name="employee_profile",
    )
    employee_number = models.CharField(max_length=50, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    department = models.CharField(max_length=100, blank=True)
    date_joined = models.DateField(null=True, blank=True)
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPES, default="full_time")
    manager = models.ForeignKey(
        "accounts.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="direct_reports",
        help_text="Another Membership at the same business - not a User directly.",
    )
    salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    def __str__(self):
        return f"{self.membership.user} - {self.job_title or 'Employee'}"
