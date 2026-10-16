# organizations/migrations/0009_mark_existing_onboarded.py
"""
Backfill for `Organization.onboarding_completed`.

The field was introduced in 0008 with `default=False`, so every
Organization that existed before that migration reads as "not
onboarded" — even though its owner has been using the app for a
while. `accounts.views.PostLoginRouterView` reads this flag to
decide whether a returning user goes to the dashboard or back into
the onboarding wizard, so without this backfill every existing user
would loop through the wizard on every login.

The rule applied: assume every pre-existing org has finished
onboarding. That's the correct assumption for the population that
predates the flag (they were already using the app), and it's safe
for future orgs because the two paths that create them —
`SignupForm.save` and `CompleteSignupForm.save` — leave the flag at
its default, which is exactly what we want for someone still working
through the wizard.

Reverse is a no-op: un-setting the flag would just recreate the loop
this migration exists to fix.
"""

from django.db import migrations


def mark_existing_as_onboarded(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")

    # No filter on `enabled_modules` — an org that finished the wizard
    # without picking any modules is still finished. See the field
    # docstring in organizations/models.py for why those two signals
    # are deliberately separate.
    updated = Organization.objects.filter(onboarding_completed=False).update(
        onboarding_completed=True
    )
    if updated:
        print(f"  Marked {updated} existing organization(s) as onboarded.")


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0008_organization_onboarding_completed_and_more"),
    ]

    operations = [
        migrations.RunPython(
            mark_existing_as_onboarded,
            migrations.RunPython.noop,
        ),
    ]