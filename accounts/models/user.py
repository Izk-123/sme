from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Authentication only. Personal identity, business membership, role,
    and employment details now live in UserProfile, Membership, Role,
    and EmployeeProfile respectively - see the other files in this
    package. Don't add business-specific fields back onto this model;
    that's exactly the mixing this refactor is undoing.
    """

    must_change_password = models.BooleanField(
        default=False,
        help_text="Forces a password change on next login. Set automatically "
        "for employees who accept an invitation - see accounts.models.Invitation.",
    )

    def __str__(self):
        return self.username or self.email or f"User #{self.pk}"

    @property
    def organization(self):
        """
        Backward-compatible shortcut for templates/tests: the
        organization of the user's first active membership. Views should
        prefer `request.organization`, set by
        core.middleware.CurrentMembershipMiddleware, since it respects
        which business the user is currently acting as (relevant once a
        user has more than one membership).
        """
        membership = self.memberships.filter(is_active=True).select_related("organization").first()
        return membership.organization if membership else None

    @property
    def role(self):
        """Backward-compatible shortcut - see the `organization` docstring above."""
        membership = self.memberships.filter(is_active=True).select_related("role").first()
        return membership.role if membership else None
