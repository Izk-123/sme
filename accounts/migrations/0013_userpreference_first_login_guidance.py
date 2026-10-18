# accounts/migrations/0013_userpreference_first_login_guidance.py
"""
Add the two flags that drive first-login guidance to UserPreference:

  * tour_seen               — the 3-slide welcome modal has been shown
  * getting_started_dismissed — the owner hid the dashboard checklist

Both default to False so new users get the full experience. Users who
already existed before this feature shipped have their tour suppressed
by the follow-up data migration 0014.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    # 0012_alter_userprofile_email_verified is the actual tip of the
    # accounts migration graph as of this change. The previous draft of
    # this file depended on a non-existent "006_userprofile_email_normalized"
    # which made `migrate` abort with NodeNotFoundError.
    dependencies = [
        ("accounts", "0012_alter_userprofile_email_verified"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreference",
            name="tour_seen",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Set once the user has finished, skipped, or closed "
                    "the welcome modal — see core.views.GetStartedActionView."
                ),
            ),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="getting_started_dismissed",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Set when the owner hides the dashboard 'Get started' "
                    "checklist. Independent of tour_seen."
                ),
            ),
        ),
    ]