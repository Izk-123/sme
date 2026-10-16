# accounts/migrations/0011_account_linking_patch.py
"""
Account-linking patch — adds the two-flag design and canonical email.

Three changes:

  1. Schema:
       * UserProfile.email_address_verified — BooleanField, default False.
         Distinct from the existing `email_verified`, which means
         "contact confirmed" (either channel). This new flag means
         "the email ADDRESS was proven, i.e. the user clicked a link
         we delivered by email." Required for Google account linking;
         see accounts/adapters.py.

       * User.email_normalized — CharField, indexed, default "".
         Canonical form of the email address that collapses Gmail
         dot/plus variations. Used for identity matching.

  2. Data backfill (part 1 — normalize existing emails):
       Every User.email is run through the same normalization rule
       that new saves use, so pre-existing rows match the code path.

  3. Data backfill (part 2 — mark email-proven profiles):
       Profiles where `email_verified=True` AND the preferred
       verification channel was email get
       `email_address_verified=True`. This is a heuristic: we don't
       have a historical record of which channel each confirmation
       link actually arrived through, but "they said email at signup
       and they're confirmed" is right for the overwhelming majority.
       Accounts that preferred WhatsApp are deliberately left at
       `email_address_verified=False` — those users can prove their
       email later via Settings → Security.

     Accounts created between the code deploy and the migration running
     will have `email_normalized=""`. The signup form fills it on
     save, so this is only a transient state; nothing reads it until
     a Google sign-in runs the matching query, and the query falls
     back to a case-insensitive exact match on `email` for rows whose
     canonical form is empty.
"""

from django.db import migrations, models


def _normalize_email(email):
    """
    Inlined from accounts.email_normalization.normalize_email.

    Migrations must be self-contained — importing the utility module
    would mean a future refactor of that function could break this
    historical migration when replayed on a fresh database. The rule
    itself has been stable since it was written; if it ever changes,
    this copy stays frozen at the version that was in force here.

    Behaviour:
      * lowercase
      * strip whitespace
      * remove +tag from local part (RFC 5233)
      * for gmail.com / googlemail.com: remove all dots from local
        part and canonicalise googlemail.com to gmail.com
    """
    if not email:
        return ""
    email = email.strip().lower()
    if "@" not in email:
        return email
    local, _, domain = email.partition("@")
    if not local or not domain:
        return email
    if "+" in local:
        local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def backfill_normalized_and_proven(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    UserProfile = apps.get_model("accounts", "UserProfile")

    # ---- 1. Populate User.email_normalized ---------------------------
    #
    # Batched by iterating with .iterator() so a large user table
    # doesn't blow memory, and bulk_update so we make one UPDATE per
    # 500 rows rather than one per row.
    batch = []
    for user in User.objects.only("id", "email", "email_normalized").iterator(
        chunk_size=500
    ):
        if not user.email:
            continue
        normalized = _normalize_email(user.email)
        if user.email_normalized != normalized:
            user.email_normalized = normalized
            batch.append(user)
        if len(batch) >= 500:
            User.objects.bulk_update(batch, ["email_normalized"], batch_size=500)
            batch.clear()
    if batch:
        User.objects.bulk_update(batch, ["email_normalized"], batch_size=500)

    # ---- 2. Mark email-proven profiles -------------------------------
    #
    # Rule: preferred channel was email AND contact is already
    # confirmed. See the module docstring for why this is the correct
    # heuristic and what edge cases it may misclassify.
    updated = UserProfile.objects.filter(
        email_verified=True,
        preferred_verification_channel="email",
        email_address_verified=False,
    ).update(email_address_verified=True)

    if updated:
        print(
            f"  Marked {updated} profile(s) as email_address_verified "
            f"(they verified via the email channel)."
        )


def noop_reverse(apps, schema_editor):
    """
    Reverse is a no-op.

    Un-setting email_address_verified would recreate the "locked out
    of Google linking" state this patch exists to fix. Un-normalizing
    emails would be lossy (the original spelling is still on
    User.email — only the canonical copy is dropped). Doing nothing
    on reverse is the correct behaviour here.
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_userprofile_preferred_verification_channel_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="email_address_verified",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Set only when the email address is proven, i.e. the "
                    "user clicked a link delivered by email. Verifying via "
                    "WhatsApp does NOT set this. Required for Google "
                    "account linking."
                ),
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="email_normalized",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text=(
                    "Canonical form of `email`, populated on save. Used for "
                    "identity matching that survives Gmail dot/plus "
                    "variations."
                ),
                max_length=254,
            ),
        ),
        migrations.RunPython(backfill_normalized_and_proven, noop_reverse),
    ]