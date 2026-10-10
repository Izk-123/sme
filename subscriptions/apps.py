# subscriptions/apps.py
from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    name = "subscriptions"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import subscriptions.signals  # noqa
