# subscriptions/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver

from organizations.models import Organization

from .services import start_trial


@receiver(post_save, sender=Organization)
def create_trial_subscription(sender, instance, created, **kwargs):
    """
    Every new business starts on a full-featured trial (see
    subscriptions.services.start_trial and the design discussion's
    "let them see value first" reasoning) rather than Free by default.

    Lives here (not in accounts/signals.py) so it listens on the model
    it actually needs - Organization, not User - and so the accounts
    app doesn't need to import anything from subscriptions at all.
    """
    if created:
        start_trial(instance)
