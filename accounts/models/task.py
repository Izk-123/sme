from django.conf import settings
from django.db import models


class Task(models.Model):
    """
    Employee self-service task list (FR-05). Assigning tasks is
    owner-side via /admin/ for now - no dedicated "assign task" UI yet.
    Employees view and mark their own tasks complete on the Self-Service
    Portal - see accounts.views.SelfServicePortalView.
    """

    membership = models.ForeignKey(
        "accounts.Membership",
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_completed", "due_date", "-created_at"]

    def __str__(self):
        return self.title
