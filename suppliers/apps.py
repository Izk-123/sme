from django.apps import AppConfig


class SuppliersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "suppliers"

    def ready(self):
        # Importing the module registers the post_save / pre_save /
        # post_delete receivers that keep Supplier.outstanding_balance
        # in sync with its related rows.
        import suppliers.signals  # noqa: F401