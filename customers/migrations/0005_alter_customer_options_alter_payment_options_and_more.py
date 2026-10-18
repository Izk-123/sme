import django.core.validators
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0004_payment'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='customer',
            options={'ordering': ['name']},
        ),
        migrations.AlterModelOptions(
            name='payment',
            options={'ordering': ['-created_at']},
        ),
        migrations.AddField(
            model_name='customer',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Deactivate instead of deleting, so historical sales and payments keep their link.'),
        ),
        migrations.AddField(
            model_name='customer',
            name='opening_balance',
            field=models.DecimalField(decimal_places=2, default=0, help_text='What this customer owed before they were added to ChumaFlow.', max_digits=12),
        ),
        migrations.AlterField(
            model_name='customer',
            name='outstanding_balance',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Derived: opening balance + credit sales - payments. Do not edit by hand.', max_digits=12),
        ),
        migrations.AlterField(
            model_name='payment',
            name='amount',
            field=models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))]),
        ),
        migrations.AlterField(
            model_name='payment',
            name='reference',
            field=models.CharField(blank=True, help_text='Optional reference, e.g. invoice or transaction ID.', max_length=100),
        ),
    ]