import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tx_ref", models.CharField(default=uuid.uuid4, max_length=64, unique=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(default="MWK", max_length=10)),
                ("provider", models.CharField(default="paychangu", max_length=20)),
                ("status", models.CharField(
                    choices=[("pending", "Pending"), ("success", "Success"), ("failed", "Failed")],
                    default="pending", max_length=20,
                )),
                ("applied", models.BooleanField(default=False)),
                ("raw_verification", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="subscriptions.subscriptionplan")),
                ("subscription", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payment_transactions", to="subscriptions.subscription")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
