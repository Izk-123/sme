# accounts/models.py (add these to the end of the file)
from django.db import models
from django.conf import settings

class UserPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    theme = models.CharField(max_length=20, choices=[("system", "System"), ("light", "Light"), ("dark", "Dark")], default="system")
    language = models.CharField(max_length=10, default="en")
    timezone = models.CharField(max_length=100, default="Africa/Blantyre")
    compact_mode = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.user.username} preferences"

class NotificationPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    # Sales alerts
    daily_sales_summary = models.BooleanField(default=True)
    # Inventory alerts
    low_stock_alert = models.BooleanField(default=True)
    out_of_stock_alert = models.BooleanField(default=True)
    # Customer alerts
    payment_overdue = models.BooleanField(default=True)
    customer_payment_received = models.BooleanField(default=True)
    # Security alerts
    new_login_alert = models.BooleanField(default=True)
    password_changed_alert = models.BooleanField(default=True)
    # Channels
    push_notifications = models.BooleanField(default=True)
    email_notifications = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.user.username} notification settings"