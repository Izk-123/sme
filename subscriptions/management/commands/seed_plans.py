from django.core.management.base import BaseCommand

from subscriptions.models import SubscriptionPlan

# Feature flags a plan can carry. Kept as a flat dict (see
# SubscriptionPlan.features) so adding a new one is a data change, not
# a migration - views check with subscription.has_feature("slug").
PLANS = [
    {
        "name": "Free", "slug": "free", "sort_order": 0,
        "price_monthly": 0, "price_annual": 0,
        "max_users": 1, "max_products": 10, "max_branches": 1, "max_transactions_month": 50,
        "features": {},
    },
    {
        "name": "Starter", "slug": "starter", "sort_order": 1,
        "price_monthly": 10000, "price_annual": 100000,
        "max_users": 3, "max_products": 500, "max_branches": 1, "max_transactions_month": 1000,
        "features": {"barcode": True, "reports": True, "receipts": True, "credit_tracking": True},
    },
    {
        "name": "Business", "slug": "business", "sort_order": 2,
        "price_monthly": 25000, "price_annual": 250000,
        # 0 = unlimited, see SubscriptionPlan.get_limit()
        "max_users": 10, "max_products": 0, "max_branches": 3, "max_transactions_month": 0,
        "features": {
            "barcode": True, "reports": True, "receipts": True, "credit_tracking": True,
            "advanced_reports": True, "stocktake": True, "purchase_orders": True,
            "customer_statements": True, "multi_payment_methods": True,
        },
    },
    {
        "name": "Professional", "slug": "professional", "sort_order": 3,
        "price_monthly": 50000, "price_annual": 500000,
        "max_users": 0, "max_products": 0, "max_branches": 0, "max_transactions_month": 0,
        "features": {
            "barcode": True, "reports": True, "receipts": True, "credit_tracking": True,
            "advanced_reports": True, "stocktake": True, "purchase_orders": True,
            "customer_statements": True, "multi_payment_methods": True,
            "multi_branch": True, "api_access": True, "approval_workflows": True, "priority_support": True,
        },
    },
]


class Command(BaseCommand):
    help = "Seed the default subscription plans (safe to run repeatedly - updates existing rows by slug)."

    def handle(self, *args, **options):
        for data in PLANS:
            plan, created = SubscriptionPlan.objects.update_or_create(
                slug=data["slug"], defaults=data,
            )
            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action}: {plan.name}"))
