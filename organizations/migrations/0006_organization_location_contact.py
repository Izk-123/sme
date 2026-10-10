# Fix the dependency below to match your actual latest organizations migration
# (referenced elsewhere in this project as 0004_organization_business_size_and_more,
# possibly followed by 0005_remove_organization_subscription if you applied that one).
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0004_organization_business_size_and_more"),
    ]

    operations = [
        migrations.AddField(model_name="organization", name="address", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="organization", name="city", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="organization", name="phone_number", field=models.CharField(blank=True, max_length=20)),
    ]
