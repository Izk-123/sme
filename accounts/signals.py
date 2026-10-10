# accounts/signals.py
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import NotificationPreference, UserPreference

User = get_user_model()


@receiver(post_save, sender=User)
def create_user_preferences(sender, instance, created, **kwargs):
    if created:
        UserPreference.objects.create(user=instance)
        NotificationPreference.objects.create(user=instance)


# Trial-subscription creation used to live here too, but it was never
# actually wired up (no @receiver decorator, and it assumed `instance`
# was an Organization while being attached to User's post_save - it
# wouldn't have worked even if connected). That logic now lives in
# subscriptions/signals.py, listening on Organization's post_save
# instead, where the assumption is actually correct. Keeping it here
# also risked a circular import (accounts -> subscriptions.models) for
# no benefit, since accounts/signals.py only needs to know about User.
