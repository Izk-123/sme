import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        # Fix me if your organizations app's latest migration has a
        # different number - this just needs to run after Organization exists.
        ("organizations", "0004_organization_business_size_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField(max_length=100, unique=True)),
                ("price_monthly", models.DecimalField(decimal_places=2, max_digits=12)),
                ("price_annual", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("max_users", models.PositiveIntegerField(default=1, help_text="0 = unlimited")),
                ("max_products", models.PositiveIntegerField(default=10, help_text="0 = unlimited")),
                ("max_branches", models.PositiveIntegerField(default=1, help_text="0 = unlimited")),
                ("max_transactions_month", models.PositiveIntegerField(default=50, help_text="0 = unlimited")),
                ("features", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["sort_order", "price_monthly"]},
        ),
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(
                    choices=[("trialing", "Trialing"), ("active", "Active"), ("grace", "Grace Period"),
                             ("restricted", "Restricted"), ("cancelled", "Cancelled")],
                    default="trialing", max_length=20,
                )),
                ("trial_end", models.DateTimeField(blank=True, null=True)),
                ("current_period_end", models.DateTimeField(blank=True, null=True)),
                ("grace_end", models.DateTimeField(blank=True, null=True)),
                ("cancel_at_period_end", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE, related_name="subscription",
                    to="organizations.organization",
                )),
                ("plan", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="subscriptions",
                    to="subscriptions.subscriptionplan",
                )),
            ],
        ),
        migrations.CreateModel(
            name="Invoice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("invoice_number", models.CharField(max_length=50, unique=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("status", models.CharField(
                    choices=[("pending", "Pending"), ("paid", "Paid"), ("failed", "Failed")],
                    default="pending", max_length=20,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("subscription", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="invoices",
                    to="subscriptions.subscription",
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("payment_method", models.CharField(
                    choices=[("airtel_money", "Airtel Money"), ("tnm_mpamba", "TNM Mpamba"),
                             ("bank", "Bank"), ("card", "Card"), ("other", "Other")],
                    max_length=20,
                )),
                ("transaction_ref", models.CharField(blank=True, max_length=100)),
                ("status", models.CharField(default="success", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("invoice", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="payments",
                    to="subscriptions.invoice",
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
