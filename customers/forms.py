"""
Forms for the customers app.

Both forms depend on BootstrapFormMixin (core/forms.py) for widget CSS.
Neither exposes `organization` as a field — it's injected by the view from
request.organization, never round-tripped through HTML.
"""
from decimal import Decimal

from django import forms

from core.forms import BootstrapFormMixin
from .models import Customer, Payment


class CustomerForm(BootstrapFormMixin, forms.ModelForm):
    """
    Create or edit a customer.

    `opening_balance` (not `outstanding_balance`) is the editable field.
    outstanding_balance is derived from it plus sales minus payments and
    is recalculated in the view after save.
    """

    opening_balance = forms.DecimalField(
        max_digits=12, decimal_places=2,
        min_value=0, initial=0, required=False,
        help_text=(
            "Amount this customer already owed you before using ChumaFlow. "
            "Leave at 0 for a new customer."
        ),
    )

    class Meta:
        model = Customer
        fields = ["name", "phone", "location", "opening_balance"]

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)

        # Fresh customer defaults to 0 owed. On an edit form the existing
        # value is on the instance, so we must not overwrite it.
        if not self.instance.pk:
            self.fields["opening_balance"].initial = 0

    def clean_opening_balance(self):
        # An empty box would otherwise arrive as None and blow up on save
        # against the non-nullable column. Treat it as 0.
        return self.cleaned_data.get("opening_balance") or Decimal("0")


class PaymentForm(BootstrapFormMixin, forms.ModelForm):
    """
    Record a payment received from a customer.

    The customer dropdown is scoped to the current organization AND to
    active customers only — a deactivated customer shouldn't be able to
    receive new payments.
    """

    amount = forms.DecimalField(
        max_digits=12, decimal_places=2,
        min_value=Decimal("0.01"),
    )

    class Meta:
        model = Payment
        fields = ["customer", "amount", "payment_method", "reference"]

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)

        if self.organization is not None:
            self.fields["customer"].queryset = (
                Customer.objects
                .filter(organization=self.organization, is_active=True)
                .order_by("name")
            )