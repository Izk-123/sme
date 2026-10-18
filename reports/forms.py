"""
Report forms.

MonthYearForm's year choices were computed at import time in the old
version, so after midnight on 1 January the range was stale until the
process restarted. They're computed per-request now. The month labels
are real names, not numbers.
"""
import calendar

from django import forms
from django.utils import timezone


class MonthYearForm(forms.Form):
    month = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-select"}))
    year = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.localdate()
        self.fields["month"].choices = [
            (i, calendar.month_name[i]) for i in range(1, 13)
        ]
        # One year ahead lets the owner plan; anything older than 2020
        # isn't in this system.
        self.fields["year"].choices = [(y, y) for y in range(2020, now.year + 2)]
        self.fields["month"].initial = now.month
        self.fields["year"].initial = now.year


class SalesReportForm(MonthYearForm):
    LIMIT_CHOICES = [(5, "Top 5"), (10, "Top 10"), (20, "Top 20"), (50, "Top 50")]
    limit = forms.ChoiceField(
        choices=LIMIT_CHOICES, initial=10,
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class YearForm(forms.Form):
    """Year selector for expense trends. Shows the last 6 years."""
    year = forms.ChoiceField(
        label="Year", widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.localdate()
        self.fields["year"].choices = [
            (y, y) for y in range(now.year - 5, now.year + 2)
        ]
        self.fields["year"].initial = now.year