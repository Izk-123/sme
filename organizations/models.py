# organizations/models.py
from django.db import models


class Organization(models.Model):
    BUSINESS_TYPES = [
        ("retail", "Retail / Shop"),
        ("wholesale", "Wholesale / Distribution"),
        ("manufacturing", "Manufacturing"),
        ("restaurant", "Restaurant / Food"),
        ("hospitality", "Hotel / Guesthouse"),
        ("salon", "Salon / Barbershop"),
        ("workshop", "Workshop / Repair"),
        ("services", "Professional Services"),
        ("education", "School / Training"),
        ("agriculture", "Agriculture / Agribusiness"),
        ("other", "Other"),
    ]

    SIZE_CHOICES = [
        ("micro", "Micro (1–5 employees)"),
        ("small", "Small (6–30 employees)"),
        ("medium", "Medium (31–100+ employees)"),
    ]

    name = models.CharField(max_length=200)
    business_type = models.CharField(max_length=20, choices=BUSINESS_TYPES, default="retail")
    business_size = models.CharField(max_length=20, choices=SIZE_CHOICES, default="micro")
    enabled_modules = models.JSONField(default=list, blank=True)
    currency = models.CharField(max_length=10, default="MWK")
    # New in this patch (FR-02): location/contact fields collected at
    # onboarding step 6 - see core/views.py's OnboardingStepView.
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # No `subscription` field or property here - see subscriptions.Subscription's
    # related_name="subscription" for why (a previous version of this file
    # had a duplicate/conflicting definition - already fixed, don't reintroduce it).

    def __str__(self):
        return self.name
