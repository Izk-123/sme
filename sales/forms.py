"""
Product and stock-receive forms.

ReceiveStockForm encodes the accounting for a single delivery:

  * unit_cost is REQUIRED. Without it the delivery has no cost, so
    both the product's weighted average (used for future profit) and
    the supplier balance (which counts what was owed) become guesses.

  * paid_now records how much was handed over on the spot. If it's
    less than the delivery total, a supplier must be chosen so the
    unpaid remainder is recorded as owed. If it's zero, the delivery
    is on credit. If it equals the total, no debt is created and no
    supplier is strictly needed (but one can still be chosen to keep
    the audit trail).

  * Both the product and supplier querysets are scoped to the current
    organization. Inactive suppliers are hidden — new deliveries
    shouldn't reopen an account that's been deliberately closed.
"""
from decimal import Decimal

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
            "name":               forms.TextInput(attrs={"class": "form-control"}),
            "sku":                forms.TextInput(attrs={"class": "form-control"}),
            "category":           forms.TextInput(attrs={"class": "form-control"}),
            "price":              forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "cost_price":         forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "stock_quantity":     forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "low_stock_threshold": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "barcode":            forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cost_price"].required = True
        self.fields["cost_price"].help_text = (
            "What you paid per unit. Used to calculate your real profit."
        )


class ReceiveStockForm(forms.Form):
    """
    Record a delivery of stock.

    A delivery has TWO costs, kept deliberately separate:

      * The supplier cost — what you paid for this delivery. It's the
        amount that goes on your supplier balance. Required, because
        without it the balance and the future profit are guesses.

      * The product cost — a running weighted average used for profit
        on FUTURE sales. Updated by the view, not this form.

    The two are updated separately so a change to one never retroactively
    rewrites the other.
    """

    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        label="Product",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    quantity = forms.IntegerField(
        min_value=1,
        label="Quantity received",
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )
    unit_cost = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=0,
        label="Cost per unit",
        help_text="What you paid, or will pay, for ONE unit on this delivery.",
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.none(), required=False, label="Supplier",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    paid_now = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False,
        initial=0, label="Paid now",
        help_text=(
            "Cash or mobile money you handed over on delivery. "
            "Leave 0 if you will pay later."
        ),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)
        if self.organization:
            self.fields["product"].queryset = (
                Product.objects.filter(organization=self.organization).order_by("name")
            )
            # Inactive suppliers can't receive NEW deliveries — their
            # history and balance are preserved, but they're not open
            # for new business.
            self.fields["supplier"].queryset = (
                Supplier.objects
                .filter(organization=self.organization, is_active=True)
                .order_by("name")
            )

    def clean(self):
        data = super().clean()
        qty = data.get("quantity")
        cost = data.get("unit_cost")
        paid = data.get("paid_now") or Decimal("0")
        supplier = data.get("supplier")

        if qty is None or cost is None:
            # Field-level errors will already show; nothing more to add.
            return data

        total = qty * cost

        if paid > total:
            self.add_error(
                "paid_now",
                f"You can't pay more than this delivery costs (MK{total:,.0f}).",
            )
        elif paid < total and supplier is None:
            self.add_error(
                "supplier",
                "Choose the supplier so the unpaid part is recorded as owed.",
            )

        return data