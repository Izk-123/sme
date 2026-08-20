# accounts/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import UserPreference, NotificationPreference

User = get_user_model()

@receiver(post_save, sender=User)
def create_user_preferences(sender, instance, created, **kwargs):
    if created:
        UserPreference.objects.create(user=instance)
        NotificationPreference.objects.create(user=instance)