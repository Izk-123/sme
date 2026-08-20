# organizations/models.py
from django.db import models

class Organization(models.Model):
    BUSINESS_TYPES = [
        ("retail", "Retail / Shop"),
        ("wholesale", "Wholesale / Distribution"),
        ("manufacturing", "Manufacturing"),
        ("restaurant", "Restaurant / Food"),
        ("services", "Services"),
        ("agriculture", "Agriculture"),
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
    enabled_modules = models.JSONField(default=list, blank=True)  # e.g. ["sales", "inventory", ...]
    currency = models.CharField(max_length=10, default="MWK")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name