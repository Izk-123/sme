from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_identitydocument_document_photo"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="email_verified",
            field=models.BooleanField(
                default=False,
                help_text="Set when the user clicks the link in their verification email - see accounts.emails.",
            ),
        ),
    ]
