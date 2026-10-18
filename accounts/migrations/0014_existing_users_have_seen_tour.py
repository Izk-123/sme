# accounts/migrations/0014_existing_users_have_seen_tour.py
"""
Users who already use the app must NOT be shown the welcome modal on
their next login — they've obviously already figured the app out.

So this one-shot data migration sets tour_seen=True on every existing
UserPreference row. Rows created *after* this migration keep the field
default (False), which means new users still get the guided tour.

`getting_started_dismissed` is deliberately left at its default (False):
existing owners benefit from seeing the checklist, because even a
long-time user may have steps left undone (e.g. no customer recorded
yet). Hiding it is a one-click action for anyone who finds it noise.
"""

from django.db import migrations


def existing_users_have_seen_it(apps, schema_editor):
    UserPreference = apps.get_model("accounts", "UserPreference")
    # `.update()` is a single SQL statement — no iteration, no N+1.
    updated = UserPreference.objects.update(tour_seen=True)
    if updated:
        print(
            f"  Set tour_seen=True on {updated} existing UserPreference row(s)."
        )


class Migration(migrations.Migration):

    # Depends on the schema migration that actually adds the field.
    dependencies = [
        ("accounts", "0013_userpreference_first_login_guidance"),
    ]

    operations = [
        migrations.RunPython(
            existing_users_have_seen_it,
            migrations.RunPython.noop,   # intentionally non-reversible
        ),
    ]