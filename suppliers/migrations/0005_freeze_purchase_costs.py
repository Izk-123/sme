"""
One-time freeze of purchase costs.

Before this migration, StockMovement.unit_cost was null for every row,
so Supplier.update_balance() fell back to the product's CURRENT cost.
That meant a supplier balance changed whenever a product's cost moved,
which is wrong: the supplier was owed what was agreed at the time.

This migration copies product.cost_price into unit_cost once. From now
on, update_balance() prefers unit_cost and the balance stops moving.
Rows whose product has no cost_price (None) stay at None — they'll
still fall back, but that's honest (the cost is genuinely unknown).
"""
from django.db import migrations


def freeze(apps, schema_editor):
    StockMovement = apps.get_model("sales", "StockMovement")
    qs = (
        StockMovement.objects
        .filter(movement_type="purchase", unit_cost__isnull=True)
        .select_related("product")
    )
    for m in qs.iterator():
        m.unit_cost = m.product.cost_price
        m.save(update_fields=["unit_cost"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("suppliers", "0004_supplier_opening_balance"),
        # Depends on the migration that added StockMovement.unit_cost.
        # Check your sales migrations — the last one before this file.
        ("sales", "0008_alter_sale_options_sale_created_by_and_more"),
    ]

    operations = [
        migrations.RunPython(freeze, noop),
    ]