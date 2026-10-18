"""
ExpenseForm.

Two design choices that need explaining:

1. `category_name` is a free-text CharField, not a ModelChoiceField.
   Users type an existing category name (suggested via <datalist>) or
   invent a new one on the spot; save() does a case-insensitive
   get-or-create scoped to the organization. The field is deliberately
   NOT named `category`, because ModelForm._post_clean() assigns
   cleaned_data[name] straight onto the instance for any field listed
   in Meta.fields — `instance.category = "Packaging"` would raise.

2. `on_credit` requires a supplier. Without a supplier, an unpaid
   expense has nowhere to be owed to. The form blocks that
   combination and, when on_credit is True, clears payment_method
   (nothing was paid). The supplier's balance then picks the row up
   via Expense.on_credit in Supplier.update_balance().
"""
from decimal import Decimal

from django import forms

from suppliers.models import Supplier

from .models import Expense, ExpenseCategory


# Names people type when they mean "stock I resell". Not an expense —
# that flow belongs to Receive Stock, where it becomes cost of goods
# at sale time. Blocking here is a soft guard: it catches the most
# common double-count without pretending to be exhaustive.
BLOCKED_CATEGORY_NAMES = {
    "purchases", "purchase", "stock", "stock purchase",
    "inventory", "goods", "goods for resale",
}


class ExpenseForm(forms.ModelForm):
    category_name = forms.CharField(
        label="Category",
        max_length=100,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "list": "expense-category-options",
            "autocomplete": "off",
            "placeholder": "e.g. Packaging, Rent, Transport…",
        }),
        help_text=(
            "Start typing to pick an existing category, or enter a new "
            "name to create one."
        ),
    )

    class Meta:
        model = Expense
        # `category` intentionally omitted — see module docstring.
        fields = [
            "date", "description", "amount", "supplier",
            "on_credit", "payment_method",
        ]
        widgets = {
            "date":           forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "description":    forms.TextInput(attrs={"class": "form-control"}),
            "amount":         forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "supplier":       forms.Select(attrs={"class": "form-select"}),
            "on_credit":      forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "payment_method": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)

        # Declared fields append to the end of the form; re-assert
        # the visual order the template expects.
        self.order_fields([
            "date", "category_name", "description", "amount",
            "supplier", "on_credit", "payment_method",
        ])

        # Names for the <datalist> suggestions.
        self.category_names = []
        if self.organization:
            self.category_names = list(
                self.organization.expense_categories
                .order_by("name")
                .values_list("name", flat=True)
            )
            self.fields["supplier"].queryset = (
                Supplier.objects
                .filter(organization=self.organization)
                .order_by("name")
            )

        self.fields["supplier"].required = False
        self.fields["supplier"].empty_label = "— None (rent, salaries, utilities…) —"

        # Editing an existing expense: seed the text field with the
        # current category's name so it appears prefilled.
        if self.instance and self.instance.pk and self.instance.category_id:
            self.fields["category_name"].initial = self.instance.category.name

    def clean_category_name(self):
        name = self.cleaned_data["category_name"].strip()
        if not name:
            return name
        if name.lower() in BLOCKED_CATEGORY_NAMES:
            raise forms.ValidationError(
                "Stock you buy to resell is not an expense. "
                "Record it under Receive Stock instead."
            )
        return name

    def clean(self):
        data = super().clean()
        on_credit = data.get("on_credit")
        supplier = data.get("supplier")

        if on_credit and not supplier:
            self.add_error(
                "supplier",
                "Choose the supplier you still owe for this expense.",
            )

        if on_credit:
            # Nothing was paid. Clear the method so the cash report
            # doesn't count this expense as money out.
            data["payment_method"] = ""

        return data

    def save(self, commit=True):
        expense = super().save(commit=False)

        name = (self.cleaned_data.get("category_name") or "").strip()
        org = self.organization or expense.organization

        if org and name:
            # Case-insensitive match so "Packaging" and "packaging"
            # don't become two rows. `.first()` rather than `.get()`
            # because ExpenseCategory has no unique_together and
            # pre-existing data may contain duplicates.
            category = (
                ExpenseCategory.objects
                .filter(organization=org, name__iexact=name)
                .first()
            )
            if category is None:
                category = ExpenseCategory.objects.create(
                    organization=org, name=name,
                )
            expense.category = category

        if commit:
            expense.save()
        return expense