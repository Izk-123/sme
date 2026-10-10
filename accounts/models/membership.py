from django.conf import settings
from django.db import models


class Membership(models.Model):
    """
    Links a User to an Organization with a Role. This replaces the old
    User.organization / User.role fields directly - a user can now hold
    more than one active membership (owner of one business, cashier at
    another), which a single FK on User could never represent.

    Do not read organization/role off User for anything that needs to be
    correct when a user belongs to multiple businesses - use this model,
    or request.membership / request.organization set by
    core.middleware.CurrentMembershipMiddleware for the business the user
    is currently acting as.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "organization"], name="unique_membership_per_org"),
        ]
        ordering = ["-joined_at"]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"
