# notifications/models.py
from django.db import models
from django.conf import settings
from organizations.models import Organization

class Notification(models.Model):
    TYPES = [
        ("info", "Info"),
        ("success", "Success"),
        ("warning", "Warning"),
        ("danger", "Danger"),
    ]
    
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=TYPES, default="info")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # Optional link, e.g., redirect to specific sale or product
    action_url = models.CharField(max_length=500, blank=True)
    
    class Meta:
        ordering = ['-created_at']