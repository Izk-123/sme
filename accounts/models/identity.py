from django.conf import settings
from django.db import models


class IdentityDocument(models.Model):
    """
    Optional identity verification. Deliberately NOT required at
    signup or invitation-acceptance time - this market includes a lot of
    informal businesses, and gating basic account creation on a National
    ID / Passport / Business Registration would turn a simple business
    app into a formal-registration system. A business can add these
    later for whichever employees actually need them verified.
    """

    DOCUMENT_TYPES = [
        ("national_id", "National ID"),
        ("passport", "Passport"),
        ("driving_license", "Driving Licence"),
        ("other", "Other"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="identity_documents",
    )
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPES)
    document_number = models.CharField(max_length=100)
    document_photo = models.ImageField(upload_to="identity_documents/", null=True, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    issuing_country = models.CharField(max_length=100, default="Malawi")
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_type"]

    @property
    def masked_number(self):
        """
        Never display the full document number in the UI (see the
        module docstring) - only the last 4 characters, e.g. '••••1234'.
        """
        number = self.document_number
        if len(number) <= 4:
            return "•" * len(number)
        return "•" * (len(number) - 4) + number[-4:]

    def __str__(self):
        return f"{self.get_document_type_display()}: {self.document_number}"
