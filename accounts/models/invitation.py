import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def _generate_token():
    return secrets.token_urlsafe(32)


class Invitation(models.Model):
    """
    An owner-issued invite to join their business, replacing the old
    flow of generating a temporary password and handing it over
    directly. No email server or SMS gateway required: the owner shares
    the invite link however they'd normally reach the employee (WhatsApp,
    SMS, in person), and the employee picks their own password when they
    open it - see accounts.views.AcceptInvitationView.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("expired", "Expired"),
        ("revoked", "Revoked"),
    ]

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    role = models.ForeignKey("accounts.Role", on_delete=models.PROTECT)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="invitations_sent",
    )
    full_name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    token = models.CharField(max_length=64, unique=True, default=_generate_token)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations_accepted",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    @property
    def is_valid(self):
        return self.status == "pending" and self.expires_at > timezone.now()

    def __str__(self):
        return f"Invite: {self.full_name} -> {self.organization} ({self.status})"
