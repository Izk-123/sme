# reports/forms.py
from django import forms
from django.utils import timezone

class MonthYearForm(forms.Form):
    MONTH_CHOICES = [(i, i) for i in range(1, 13)]
    YEAR_CHOICES = [(y, y) for y in range(2020, timezone.now().year + 2)]

    month = forms.ChoiceField(
        choices=MONTH_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    year = forms.ChoiceField(
        choices=YEAR_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.now()
        self.fields["month"].initial = now.month
        self.fields["year"].initial = now.year


class SalesReportForm(MonthYearForm):
    """Adds a 'limit' field to control how many top results to show."""
    LIMIT_CHOICES = [(5, "Top 5"), (10, "Top 10"), (20, "Top 20"), (50, "Top 50")]

    limit = forms.ChoiceField(
        choices=LIMIT_CHOICES,
        initial=10,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    
class YearForm(forms.Form):
    """Simple year selector for expense trends."""
    year = forms.ChoiceField(
        label="Year",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_year = timezone.now().year
        # Show last 5 years + current year + next year (for planning)
        choices = [(y, y) for y in range(current_year - 5, current_year + 2)]
        self.fields["year"].choices = choices
        self.fields["year"].initial = current_year
