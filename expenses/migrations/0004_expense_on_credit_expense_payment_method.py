from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("expenses", "0003_alter_expense_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="expense",
            name="on_credit",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Tick if you have NOT paid this supplier yet. "
                    "Only unpaid expenses count as owed."
                ),
            ),
        ),
        migrations.AddField(
            model_name="expense",
            name="payment_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("cash", "Cash"),
                    ("airtel_money", "Airtel Money"),
                    ("tnm_mpamba", "TNM Mpamba"),
                    ("bank", "Bank Transfer"),
                ],
                help_text=(
                    "How it was paid. Needed for a real cash report. "
                    "Leave blank if 'on credit' is ticked."
                ),
                max_length=20,
            ),
        ),
    ]