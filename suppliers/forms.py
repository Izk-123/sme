"""
Supplier and SupplierPayment forms.

Two things that matter for correctness:

  * SupplierForm and SupplierPaymentForm are both scoped to an
    organization. The organization is passed from the view via
    get_form_kwargs(); without it, the supplier dropdown in the payment
    form would leak every business's supplier names.

  * SupplierForm prevents duplicate names within one business
    (case-insensitive). The is_active field is hidden on create so a
    new supplier always starts active; on edit it's shown so an owner
    can deactivate a supplier without deleting its history.
"""
from django import forms

from .models import Supplier, SupplierPayment


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = [
            "name", "phone", "email", "address",
            "opening_balance", "is_active",
        ]
        widgets = {
            "name":            forms.TextInput(attrs={"class": "form-control"}),
            "phone":           forms.TextInput(attrs={"class": "form-control"}),
            "email":           forms.EmailInput(attrs={"class": "form-control"}),
            "address":         forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "opening_balance": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "is_active":       forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)

        # A brand-new supplier is always active. Editing an existing
        # one, the checkbox lets the owner reactivate (or deactivate)
        # without deleting the row — which would erase every historical
        # purchase and expense through SET_NULL/PROTECT.
        if not self.instance.pk:
            del self.fields["is_active"]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Name is required.")

        # Same-business duplicate check. The model has no unique
        # constraint here (two businesses can both have "ABC
        # Distributors"); this validation fills that gap at the form
        # level. The .exclude(pk=...) keeps the current instance out of
        # its own duplicate check on edit.
        qs = Supplier.objects.filter(
            organization=self.organization, name__iexact=name,
        )
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                "You already have a supplier with this name."
            )

        return name


class SupplierPaymentForm(forms.ModelForm):
    class Meta:
        model = SupplierPayment
        fields = ["supplier", "date", "amount", "method", "reference", "notes"]
        widgets = {
            "supplier":  forms.Select(attrs={"class": "form-select"}),
            "date":      forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "amount":    forms.NumberInput(attrs={
                "class": "form-control", "step": "0.01", "min": "0.01",
            }),
            "method":    forms.Select(attrs={"class": "form-select"}),
            "reference": forms.TextInput(attrs={"class": "form-control"}),
            "notes":     forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)

        if self.organization:
            # Only active suppliers in this business can receive new
            # payments. Inactive ones still have history but shouldn't
            # be pickable here.
            self.fields["supplier"].queryset = (
                Supplier.objects
                .filter(organization=self.organization, is_active=True)
                .order_by("name")
            )

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount is None or amount <= 0:
            raise forms.ValidationError("Payment amount must be greater than zero.")
        return amount