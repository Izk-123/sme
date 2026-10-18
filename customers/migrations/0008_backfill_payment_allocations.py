"""
Allocate existing payments FIFO across each customer's open sales.

Without this, the ageing report would treat every historical payment
as unallocated, and every sale as fully open — the report would
overstate the 61+ bucket enormously.

After this migration, allocations exist for every payment that was
made when there was at least one open sale to allocate to. Payments
made against opening_balance only (no sale) stay unallocated, which
is correct — they show up in the "opening / credit" column.
"""
from decimal import Decimal

from django.db import migrations
from django.db.models import Sum


def backfill(apps, schema_editor):
    Payment = apps.get_model("customers", "Payment")
    PaymentAllocation = apps.get_model("customers", "PaymentAllocation")
    Sale = apps.get_model("sales", "Sale")

    for payment in Payment.objects.order_by("created_at").iterator():
        remaining = payment.amount
        if remaining <= 0:
            continue

        # Already-allocated sum per sale for this customer.
        already = dict(
            PaymentAllocation.objects
            .filter(payment__customer_id=payment.customer_id)
            .values_list("sale_id")
            .annotate(t=Sum("amount"))
        )

        sales = (
            Sale.objects
            .filter(
                organization_id=payment.organization_id,
                customer_id=payment.customer_id,
            )
            .order_by("created_at", "id")
        )

        for sale in sales:
            if remaining <= 0:
                break
            already_allocated = already.get(sale.id, Decimal("0"))
            open_amount = sale.total - sale.amount_paid - already_allocated
            if open_amount <= 0:
                continue
            take = min(open_amount, remaining)
            PaymentAllocation.objects.create(
                organization_id=payment.organization_id,
                payment_id=payment.id,
                sale_id=sale.id,
                amount=take,
            )
            remaining -= take


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0007_paymentallocation"),
        ("sales", "0013_backfill_sale_amount_paid"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]