from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("suppliers", "0003_alter_supplier_options_supplier_is_active_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplier",
            name="opening_balance",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="What you already owed this supplier before using ChumaFlow.",
                max_digits=12,
            ),
        ),
        migrations.AlterField(
            model_name="supplier",
            name="outstanding_balance",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                editable=False,
                max_digits=12,
            ),
        ),
    ]