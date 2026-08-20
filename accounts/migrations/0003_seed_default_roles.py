from django.db import migrations


def seed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for slug, name in [
        ("owner", "Owner"),
        ("cashier", "Cashier"),
        ("stock_clerk", "Stock Clerk"),
        ("accountant", "Accountant"),
    ]:
        Role.objects.get_or_create(
            organization=None,
            slug=slug,
            defaults={"name": name, "is_system": True},
        )


def unseed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(organization__isnull=True, is_system=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_remove_user_organization_remove_user_role_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_roles, unseed_roles),
    ]
