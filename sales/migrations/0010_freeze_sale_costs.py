"""
One-time freeze of sale-item costs.

SaleItem.unit_cost was added in migration 0008, but rows written before
that have None there. Reports fall back to product.cost_price for those
rows, so their profit silently changes whenever the product's cost is
updated by a stock receipt. This migration captures the current cost
ONCE so they stop moving.

Products with no cost_price stay at None — the profit is genuinely
unknown for those sales, and the reports say so.
"""
from django.db import migrations


def freeze(apps, schema_editor):
    SaleItem = apps.get_model("sales", "SaleItem")
    qs = (
        SaleItem.objects
        .filter(unit_cost__isnull=True)
        .select_related("product")
    )
    for item in qs.iterator():
        item.unit_cost = item.product.cost_price
        item.save(update_fields=["unit_cost"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        # Depends on the migration that added SaleItem.unit_cost.
        ("sales", "0008_alter_sale_options_sale_created_by_and_more"),
    ]

    operations = [
        migrations.RunPython(freeze, noop),
    ]