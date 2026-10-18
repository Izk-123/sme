import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0006_backfill_opening_balance"),
        ("organizations", "0009_mark_existing_onboarded"),
        ("sales", "0013_backfill_sale_amount_paid"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("organization", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="payment_allocations",
                    to="organizations.organization",
                )),
                ("payment", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="allocations",
                    to="customers.payment",
                )),
                ("sale", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="payment_allocations",
                    to="sales.sale",
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="paymentallocation",
            constraint=models.UniqueConstraint(
                fields=("payment", "sale"),
                name="uniq_payment_sale_allocation",
            ),
        ),
    ]