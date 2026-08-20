from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """
    Personal identity information, kept off User on purpose. Everything
    here is optional except being tied to a user - see the project
    discussion's rule: "don't collect personal data merely because you
    can, collect it because a business workflow needs it."
    """

    GENDER_CHOICES = [
        ("male", "Male"),
        ("female", "Female"),
        ("other", "Other"),
        ("prefer_not_to_say", "Prefer not to say"),
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
        max_length=150, blank=True, help_text="What to display instead of the full name, if set."
    )
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True)
    profile_photo = models.ImageField(upload_to="profile_photos/", null=True, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default="Malawi", blank=True)
    email_verified = models.BooleanField(
        default=False,
        help_text="Set when the user clicks the link in their verification email - see accounts.emails.",
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
