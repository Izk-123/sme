from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0011_merge_20261018_1027"),
    ]

    operations = [
        migrations.AddField(
            model_name="sale",
            name="amount_paid",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0"),
                help_text="Cash or mobile money received at the time of sale.",
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name="sale",
            name="due_date",
            field=models.DateField(
                blank=True, null=True,
                help_text="When the unpaid portion is due. Optional.",
            ),
        ),
        migrations.AddField(
            model_name="sale",
            name="submission_token",
            field=models.CharField(
                blank=True, max_length=64, null=True, unique=True,
                help_text="Internal idempotency token for the sale form.",
            ),
        ),
    ]