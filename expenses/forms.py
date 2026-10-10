from django import forms

from suppliers.models import Supplier

from .models import Expense


class ExpenseForm(forms.ModelForm):
    """Expense form with organization-scoped supplier and category selects."""

    class Meta:
        model = Expense
        fields = ["date", "category", "description", "amount", "supplier"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "supplier": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)

        if self.organization:
            self.fields["category"].queryset = (
                self.organization.expense_categories.all().order_by("name")
            )
            self.fields["supplier"].queryset = Supplier.objects.filter(
                organization=self.organization
            ).order_by("name")

        self.fields["supplier"].required = False
        self.fields["supplier"].empty_label = "— None (rent, salaries, utilities…) —"
