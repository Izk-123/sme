"""
Backfill opening_balance on existing customers.

Why this file exists
--------------------
Migration 0005 added `Customer.opening_balance` (default 0) alongside the
existing `outstanding_balance`. On its own, that leaves every existing
customer with opening_balance = 0 while outstanding_balance still holds
the real debt figure.

That's a landmine: the next time anything calls `update_balance()` — a
credit sale, a payment, a manual correction — it recalculates as:

    0 + sum(credit sales) - sum(payments)

...and silently overwrites outstanding_balance with a smaller number,
throwing away whatever portion of the stored balance predated ChumaFlow
(paper-ledger opening balance).

This migration walks every existing customer and computes:

    opening_balance = stored_outstanding_balance - (credit_sales - payments)

...which is exactly the figure that makes `calculate_balance()` in
customers/models.py reproduce the same value it replaced. After this runs
the two numbers agree, and stay agreeing as new sales and payments land.

Reversibility
-------------
Reverse is a no-op. We can't reconstruct "what outstanding_balance was
before this migration ran" without knowing whether the stored figure was
already correct — and it always was, because the old code wrote it
directly. Leaving opening_balance set on rollback is harmless; the only
visible effect is that calculate_balance() stays consistent.

Safety
------
Idempotent in the sense that running twice produces the same result:
opening_balance is *assigned*, not incremented. Django won't re-run an
applied migration anyway, but if you ever need to reapply it after a
squash, this property holds.
"""
from django.db import migrations
from django.db.models import Sum


def backfill_opening_balance(apps, schema_editor):
    """
    Use apps.get_model (the historical model) rather than importing the
    real Customer/Sale classes. If a future migration changes those
    models, this migration must keep working as it did the day it was
    written — historical models are what give it that guarantee.
    """
    Customer = apps.get_model("customers", "Customer")
    Payment = apps.get_model("customers", "Payment")
    Sale = apps.get_model("sales", "Sale")

    updated = 0

    for customer in Customer.objects.all():
        credit = (
            Sale.objects
            .filter(customer=customer, payment_method="credit")
            .aggregate(total=Sum("total"))["total"]
            or 0
        )
        paid = (
            Payment.objects
            .filter(customer=customer)
            .aggregate(total=Sum("amount"))["total"]
            or 0
        )

        customer.opening_balance = customer.outstanding_balance - (credit - paid)
        customer.save(update_fields=["opening_balance"])
        updated += 1

    # Printed into the `migrate` output. Useful when you want to confirm
    # the migration actually touched rows rather than silently no-op'ing
    # on an empty table.
    if updated:
        print(f"  Backfilled opening_balance on {updated} customer(s).")


class Migration(migrations.Migration):

    dependencies = [
        # The migration that added opening_balance. Must name a file that
        # actually exists — a placeholder here raises NodeNotFoundError
        # before any migration runs.
        (
            "customers",
            "0005_alter_customer_options_alter_payment_options_and_more",
        ),
        # The backfill reads Sale, so the sales tables must exist. Pinned
        # to 0001_initial rather than 0008 deliberately: the backfill only
        # touches fields that have been on Sale since the beginning
        # (total, customer, payment_method) and Payment.amount. Tying this
        # migration to a *later* sales migration would make it fail on any
        # database where sales.0008 hasn't been applied yet, for no benefit.
        ("sales", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            backfill_opening_balance,
            # Reverse is a no-op — see the module docstring.
            migrations.RunPython.noop,
        ),
    ]