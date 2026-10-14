"""Product and stock forms for ChumaFlow."""
from django import forms
from suppliers.models import Supplier
from .models import Product


class ProductForm(forms.ModelForm):
    """Product create/edit. Cost price is required so profit isn't a guess."""

    class Meta:
        model = Product
        fields = [
            "name", "sku", "category", "price", "cost_price",
            "stock_quantity", "low_stock_threshold", "barcode",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "category": forms.TextInput(attrs={"class": "form-control"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "cost_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "stock_quantity": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "low_stock_threshold": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "barcode": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cost_price"].required = True
        self.fields["cost_price"].help_text = (
            "What you paid per unit. Used to calculate your real profit."
        )


class ReceiveStockForm(forms.Form):
    """
    Receive stock against an optional supplier.

    `unit_cost` is optional. When provided, the product's cost_price is
    updated to a weighted average of old and new stock — so a shop whose
    supplier just raised prices sees future profit figures reflect that,
    without retroactively changing past sales.
    """

    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        label="Product",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    quantity = forms.IntegerField(
        min_value=1,
        label="Quantity to receive",
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    unit_cost = forms.DecimalField(
        max_digits=12, decimal_places=2,
        min_value=0, required=False,
        label="Unit cost (optional)",
        help_text="If entered, updates this product's cost price (weighted average).",
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.none(),
        required=False,
        label="Supplier (optional)",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)
        if self.organization:
            self.fields["product"].queryset = (
                Product.objects.filter(organization=self.organization).order_by("name")
            )
            self.fields["supplier"].queryset = (
                Supplier.objects.filter(organization=self.organization).order_by("name")
            )