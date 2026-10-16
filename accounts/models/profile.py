# accounts/models/profile.py
from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """
    Personal identity information, kept off User on purpose. Everything
    here is optional except being tied to a user.
    """

    GENDER_CHOICES = [
        ("male", "Male"),
        ("female", "Female"),
    ]

    # Values must stay in sync with accounts.verification.CHANNEL_EMAIL /
    # CHANNEL_WHATSAPP. Duplicated on purpose — see the note in the
    # verification module about avoiding a circular import.
    VERIFICATION_CHANNEL_CHOICES = [
        ("email", "Email"),
        ("whatsapp", "WhatsApp"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    first_name = models.CharField(max_length=150, blank=True)
    middle_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    preferred_name = models.CharField(
        max_length=150,
        blank=True,
        help_text="What to display instead of the full name, if set.",
    )
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True)
    profile_photo = models.ImageField(upload_to="profile_photos/", null=True, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default="Malawi", blank=True)

    # ------------------------------------------------------------------
    # Two verification flags, deliberately separate
    # ------------------------------------------------------------------
    #
    # `email_verified`
    #   "The account's contact information has been confirmed." Set
    #   whenever the user clicks the link from EITHER channel — email
    #   or WhatsApp. Its job is to gate the app: users with unverified
    #   contacts get held on the verify-required page by
    #   core.middleware.EmailVerificationMiddleware.
    #
    # `email_address_verified`
    #   "The EMAIL ADDRESS ITSELF was proven." Set only when the user
    #   clicks a link that arrived by email. Verifying via WhatsApp does
    #   NOT set this, because WhatsApp proves a phone number, not an
    #   inbox.
    #
    # The distinction matters for Google sign-in. Linking a Google
    # identity to an existing account requires that the *email* is
    # proven — otherwise an attacker who knows a victim's address can
    # claim it, verify their phone via WhatsApp, and then have Google
    # hand them the account. See adapters.ChumaFlowSocialAdapter.
    email_verified = models.BooleanField(
        default=False,
        help_text=(
            "Set when the user confirms their contact via any channel "
            "(email or WhatsApp) — see accounts.verification."
        ),
    )
    email_address_verified = models.BooleanField(
        default=False,
        help_text=(
            "Set only when the email address is proven, i.e. the user "
            "clicked a link delivered by email. Verifying via WhatsApp "
            "does NOT set this. Required for Google account linking."
        ),
    )

    preferred_verification_channel = models.CharField(
        max_length=20,
        choices=VERIFICATION_CHANNEL_CHOICES,
        default="email",
        help_text=(
            "How the account owner chose to receive their confirmation "
            "link at signup. Read by ResendVerificationEmailView so a "
            "resend goes out the same way the original did."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        name = " ".join(p for p in parts if p)
        return name or self.user.username

    @property
    def display_name(self):
        return self.preferred_name or self.full_name

    def __str__(self):
        return self.display_name