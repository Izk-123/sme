# sales/forms.py
from django import forms
from suppliers.models import Supplier  # <-- import the Supplier model
from .models import Product

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'sku', 'category', 'price', 'stock_quantity', 'low_stock_threshold', 'barcode']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'sku': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.TextInput(attrs={'class': 'form-control'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stock_quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'low_stock_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'barcode': forms.TextInput(attrs={'class': 'form-control'}),
        }

class ReceiveStockForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        label="Product",
        widget=forms.Select(attrs={"class": "form-select"})
    )
    quantity = forms.IntegerField(
        min_value=1,
        label="Quantity to receive",
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1})
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.none(),
        required=False,
        label="Supplier (optional)",
        widget=forms.Select(attrs={"class": "form-select"})
    )

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)
        if self.organization:
            self.fields["product"].queryset = Product.objects.filter(
                organization=self.organization
            ).order_by("name")
            self.fields["supplier"].queryset = Supplier.objects.filter(
                organization=self.organization
            ).order_by("name")