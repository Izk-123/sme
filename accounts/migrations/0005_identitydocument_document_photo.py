from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_notificationpreference_userpreference"),
    ]

    operations = [
        migrations.AddField(
            model_name="identitydocument",
            name="document_photo",
            field=models.ImageField(blank=True, null=True, upload_to="identity_documents/"),
        ),
    ]
