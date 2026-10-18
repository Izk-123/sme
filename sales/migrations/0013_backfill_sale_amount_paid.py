"""
Backfill Sale.amount_paid on existing rows.

Pre-migration sales only had payment_method. For them, a fully paid
sale means payment_method != 'credit', and a fully unpaid sale means
payment_method == 'credit'. This migration captures that fact into
amount_paid once, so Customer.calculate_balance() (which reads
total - amount_paid) reproduces the same figures as before for
existing records.

New records always set amount_paid in the sale creation view.

Note on the loop: this uses a plain Python loop rather than a single
`.update(amount_paid=F("total"))`. The F-expression form is tempting
but requires `from django.db.models import F` inside the migration,
and running that against the historical model has been a source of
subtle bugs (historical models resolve expressions differently to
current ones). For a typical SME dataset the loop is instant, and
correctness is worth more than the milliseconds.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    Sale = apps.get_model("sales", "Sale")
    for sale in Sale.objects.all().iterator():
        if sale.payment_method == "credit":
            sale.amount_paid = 0
        else:
            sale.amount_paid = sale.total
        sale.save(update_fields=["amount_paid"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0012_sale_amount_paid_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]