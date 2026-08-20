from django.conf import settings
from django.db import models


class PhoneNumber(models.Model):
    """
    A contact number for a user. Split into its own model (rather than a
    single field on User) because one person can reasonably have several
    - primary mobile, WhatsApp, work - and phone verification is a
    natural next step for this market, where email is often optional but
    a phone number rarely is.
    """

    TYPE_CHOICES = [
        ("mobile", "Mobile"),
        ("whatsapp", "WhatsApp"),
        ("work", "Work"),
        ("alternative", "Alternative"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="phone_numbers",
    )
    number = models.CharField(max_length=20)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="mobile")
    is_primary = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "type"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_primary:
            # Only one primary number per user - unset any others.
            PhoneNumber.objects.filter(user=self.user, is_primary=True).exclude(pk=self.pk).update(
                is_primary=False
            )

    def __str__(self):
        return f"{self.number} ({self.get_type_display()})"
