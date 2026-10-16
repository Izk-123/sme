# accounts/models/user.py
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Authentication only. Personal identity, business membership, role,
    and employment details live in UserProfile, Membership, Role, and
    EmployeeProfile respectively — see the other files in this package.
    Don't add business-specific fields back onto this model.
    """

    must_change_password = models.BooleanField(
        default=False,
        help_text="Forces a password change on next login. Set automatically "
        "for employees who accept an invitation - see accounts.models.Invitation.",
    )

    # ------------------------------------------------------------------
    # Canonical email for identity matching
    # ------------------------------------------------------------------
    #
    # Populated by accounts.email_normalization.normalize_email() whenever
    # the User's email is set or changed — see SignupForm.save(),
    # ProfileForm.save(), and the AcceptInvitationView.
    #
    # Indexed, not unique. Uniqueness would make sense in a greenfield
    # database, but existing data may have duplicate emails (an unverified
    # account created years ago, plus a new signup), and enforcing the
    # constraint now would fail the migration. Matching is done in
    # application logic instead, with the stricter rules in
    # adapters.ChumaFlowSocialAdapter and forms.SignupForm.
    #
    # Empty string rather than null so the index doesn't have NULL
    # semantics to worry about.
    email_normalized = models.CharField(
        max_length=254,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Canonical form of `email`, populated on save. Used for "
            "identity matching that survives Gmail dot/plus variations."
        ),
    )

    def __str__(self):
        return self.username or self.email or f"User #{self.pk}"

    @property
    def organization(self):
        """
        Backward-compatible shortcut: the organization of the user's
        first active membership. Views should prefer
        request.organization (set by CurrentMembershipMiddleware),
        which respects which business the user is currently acting as.
        """
        membership = (
            self.memberships
            .filter(is_active=True)
            .select_related("organization")
            .first()
        )
        return membership.organization if membership else None

    @property
    def role(self):
        """Backward-compatible shortcut - see the `organization` docstring."""
        membership = (
            self.memberships
            .filter(is_active=True)
            .select_related("role")
            .first()
        )
        return membership.role if membership else None