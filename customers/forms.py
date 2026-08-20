# customers/forms.py
from django import forms
from .models import Customer, Payment

class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["customer", "amount", "payment_method", "reference"]
        widgets = {
            "customer": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "payment_method": forms.Select(attrs={"class": "form-select"}),
            "reference": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)
        if self.organization:
            self.fields["customer"].queryset = Customer.objects.filter(
                organization=self.organization
            ).order_by("name")