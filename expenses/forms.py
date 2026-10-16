from django import forms

from suppliers.models import Supplier

from .models import Expense, ExpenseCategory


class ExpenseForm(forms.ModelForm):
    """
    Expense form with a free-text category field and an organization-scoped
    supplier select.

    Category is deliberately NOT a ModelChoiceField: users type the name of
    an existing category (suggested via <datalist>) or invent a new one on
    the spot. The lookup-or-create happens in save(), scoped to the
    expense's organization — so two businesses can both have a "Packaging"
    category and they won't collide.

    Why the field is called `category_name` and not `category`:
    ModelForm._post_clean() runs construct_instance() which, for any field
    listed in Meta.fields, assigns cleaned_data[name] straight onto the
    instance. If this field were named `category`, Django would try to set
    instance.category_id = "Packaging" (a string) and raise. Keeping the
    form field off the model's field name lets Django validate the string
    normally, and gives us a clean hook in save() to resolve the FK.
    """

    category_name = forms.CharField(
        label="Category",
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "list": "expense-category-options",
                "autocomplete": "off",
                "placeholder": "e.g. Packaging, Rent, Transport…",
            }
        ),
        help_text=(
            "Start typing to pick an existing category, or enter a new name "
            "to create one."
        ),
    )

    class Meta:
        model = Expense
        # `category` intentionally omitted — see class docstring.
        fields = ["date", "description", "amount", "supplier"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "supplier": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop("organization", None)
        super().__init__(*args, **kwargs)

        # Declared fields get appended to the end of the form's field
        # order; re-assert the visual order the template expects.
        self.order_fields(
            ["date", "category_name", "description", "amount", "supplier"]
        )

        # Names for the <datalist> in the template. Empty list is fine —
        # the datalist just renders no suggestions and the user types.
        self.category_names = []
        if self.organization:
            self.category_names = list(
                self.organization.expense_categories
                .order_by("name")
                .values_list("name", flat=True)
            )
            self.fields["supplier"].queryset = Supplier.objects.filter(
                organization=self.organization
            ).order_by("name")

        self.fields["supplier"].required = False
        self.fields["supplier"].empty_label = "— None (rent, salaries, utilities…) —"

        # Editing an existing expense: seed the text field with the
        # current category's name so it appears prefilled.
        if self.instance and self.instance.pk and self.instance.category_id:
            self.fields["category_name"].initial = self.instance.category.name

    def save(self, commit=True):
        expense = super().save(commit=False)

        name = (self.cleaned_data.get("category_name") or "").strip()
        # Fall back to the instance in case a future view sets it on the
        # instance without passing organization= to the form.
        org = self.organization or expense.organization

        if org and name:
            # Case-insensitive match so "packaging" and "Packaging" don't
            # become two rows. .first() rather than .get() because
            # ExpenseCategory has no unique_together — pre-existing data
            # could legitimately have duplicates.
            category = (
                ExpenseCategory.objects
                .filter(organization=org, name__iexact=name)
                .first()
            )
            if category is None:
                category = ExpenseCategory.objects.create(
                    organization=org, name=name
                )
            expense.category = category

        if commit:
            expense.save()
        return expense