from django.db import models


class Role(models.Model):
    """
    A role a Membership can carry. System roles (organization=None) are
    shared across every business and seeded once by a data migration -
    see accounts/migrations/0002_seed_default_roles.py. A business can
    later define its own custom roles (organization=<their Organization>)
    without touching the system defaults.

    Deliberately NOT building the granular Permission model yet (see
    project discussion, section 13/16) - `slug` is enough for
    RoleRequiredMixin checks today. Add a Permission model + M2M when a
    business actually needs custom per-role access, not before.
    """

    SYSTEM_ROLES = [
        ("owner", "Owner"),
        ("cashier", "Cashier"),
        ("stock_clerk", "Stock Clerk"),
        ("accountant", "Accountant"),
    ]

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="roles",
        null=True,
        blank=True,
        help_text="Blank for shared system roles available to every business. "
        "Set for a custom role a specific business created for itself.",
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    is_system = models.BooleanField(
        default=False,
        help_text="System roles are seeded automatically and can't be deleted or renamed from the UI.",
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "slug"], name="unique_role_slug_per_org"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def get_system(cls, slug):
        """The shared system role for this slug - use when seeding a new Membership."""
        return cls.objects.get(organization__isnull=True, slug=slug)
