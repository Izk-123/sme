# organizations/models.py
from django.db import models


class Organization(models.Model):
    """
    A business. Every UserProfile, Membership, Invitation, and business
    record (Product, Sale, Expense, etc.) is scoped to exactly one of
    these. A user belongs to an Organization through a Membership — see
    accounts.models.Membership — not a foreign key on User.

    Creating an Organization happens in exactly two places:
      * accounts.forms.SignupForm.save() — the local signup form.
      * accounts.forms.CompleteSignupForm.save() — the tail end of the
        Google signup flow, for a user Google created but who has no
        Membership yet.

    Neither path marks the org as onboarded — the owner does that by
    finishing the wizard. See `onboarding_completed` below.
    """

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

    # ------------------------------------------------------------------
    # Core identity
    # ------------------------------------------------------------------

    name = models.CharField(max_length=200)

    business_type = models.CharField(
        max_length=20,
        choices=BUSINESS_TYPES,
        default="retail",
        help_text=(
            "Set properly at onboarding step 1. The default exists so "
            "the Organization row can be created at signup time before "
            "the owner has answered the wizard's questions."
        ),
    )

    business_size = models.CharField(
        max_length=20,
        choices=SIZE_CHOICES,
        default="micro",
    )

    currency = models.CharField(max_length=10, default="MWK")

    # ------------------------------------------------------------------
    # Module selection
    # ------------------------------------------------------------------
    #
    # Which feature modules the owner turned on during onboarding
    # (Sales, Inventory, Expenses, Customers, Suppliers, Reports…).
    #
    # IMPORTANT: this is NOT the signal for "has this business finished
    # the onboarding wizard?" — see `onboarding_completed` below.
    # A business can complete the wizard while selecting zero modules
    # (e.g. an owner who wants to see the dashboard first and enable
    # modules later). Using `enabled_modules` as the completion signal
    # would loop that owner through the wizard forever. The two fields
    # are deliberately separate.
    #
    # Stored as a JSON list of module slug strings, e.g. ["sales",
    # "inventory"]. Both the wizard's checkbox parsing and the dashboard
    # link gating read it.
    enabled_modules = models.JSONField(default=list, blank=True)

    # ------------------------------------------------------------------
    # Onboarding completion flag
    # ------------------------------------------------------------------
    #
    # Set to True by OnboardingStepView.post() when the owner completes
    # the final wizard step.
    #
    # Read by:
    #   * core.views.OnboardingWizardView.get()   → skip the wizard
    #     entirely if it's already done.
    #   * accounts.views.PostLoginRouterView.get() → route a returning
    #     user straight to the dashboard instead of back into onboarding.
    #
    # Both of those used to consult `enabled_modules` and would send an
    # owner who finished the wizard (but picked zero modules) back
    # through it on every login. This field fixes that loop.
    onboarding_completed = models.BooleanField(
        default=False,
        help_text=(
            "Set to True once the owner finishes the onboarding wizard. "
            "Distinct from enabled_modules, which records WHICH modules "
            "are on — a business that selects zero modules has still "
            "finished onboarding."
        ),
    )

    # ------------------------------------------------------------------
    # Location / contact (collected at onboarding)
    # ------------------------------------------------------------------
    #
    # Optional in the model, all three filled at whichever onboarding
    # step collects them (see core/views.py's OnboardingStepView). The
    # fields are here rather than on UserProfile because they describe
    # the business, not the person — a chain of shops would share an
    # owner but not a phone number.

    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # ------------------------------------------------------------------
    # Notes on fields that DON'T live here
    # ------------------------------------------------------------------
    #
    # `subscription` used to be a OneToOneField on this model, and there
    # was a matching `subscription` property at one point too. Both are
    # gone — see subscriptions.models.Subscription's
    # related_name="subscription" for the single source of truth.
    # Don't reintroduce either; if you need the subscription from an
    # Organization instance, use `org.subscription` (the reverse accessor
    # the Subscription model defines).

    def __str__(self):
        return self.name