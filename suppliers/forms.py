"""Supplier forms — includes the payment recording form."""
from django import forms

from .models import Supplier, SupplierPayment


class SupplierPaymentForm(forms.ModelForm):
    """Form for recording a payment to a supplier."""

    class Meta:
        model = SupplierPayment
        fields = ["supplier", "date", "amount", "method", "reference", "notes"]
        widgets = {
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "method": forms.Select(attrs={"class": "form-select"}),
            "reference": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)
        if self.organization:
            self.fields["supplier"].queryset = Supplier.objects.filter(
                organization=self.organization
            ).order_by("name")
