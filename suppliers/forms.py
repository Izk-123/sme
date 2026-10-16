"""Supplier forms — Supplier create/edit, and the payment recording form."""
from django import forms

from .models import Supplier, SupplierPayment


class SupplierForm(forms.ModelForm):
    """
    Create / edit a supplier.

    Used by both SupplierCreateView and SupplierUpdateView, so it must
    not assume the instance is new. The organization FK is NOT a form
    field — the view stamps it from get_organization() so a crafted
    POST can never plant a supplier in another tenant.
    """

    class Meta:
        model = Supplier
        fields = ["name", "phone", "email", "address"]
        widgets = {
            "name":    forms.TextInput(attrs={"class": "form-control"}),
            "phone":   forms.TextInput(attrs={"class": "form-control"}),
            "email":   forms.EmailInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def clean_name(self):
        # Django's CharField validation accepts a whitespace-only string.
        # Strip it here so "   " can't become a supplier called "   ".
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Name is required.")
        return name


class SupplierPaymentForm(forms.ModelForm):
    """
    Record a payment made *to* a supplier — reduces what we owe them.

    The supplier queryset is scoped to the caller's organization in
    __init__, so the dropdown can't leak other tenants' suppliers
    (and a hand-crafted POST is rejected by full_clean, not just by
    the <select> being empty).
    """

    class Meta:
        model = SupplierPayment
        fields = ["supplier", "date", "amount", "method", "reference", "notes"]
        widgets = {
            "supplier":  forms.Select(attrs={"class": "form-select"}),
            "date":      forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "amount":    forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "method":    forms.Select(attrs={"class": "form-select"}),
            "reference": forms.TextInput(attrs={"class": "form-control"}),
            "notes":     forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)
        if self.organization:
            self.fields["supplier"].queryset = (
                Supplier.objects
                .filter(organization=self.organization)
                .order_by("name")
            )