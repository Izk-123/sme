# Gap-analysis patch (FR-01 to FR-05) - apply on top of what you already have

My sandbox reset mid-conversation, so I lost the working tree. Everything
below is either a **brand-new file** (safe to drop in as-is - see the
folders alongside this file) or an **exact snippet to add** to a file
you already have from earlier zips. I'm not reprinting those files in
full, to avoid accidentally overwriting correct code with a
memory-reconstructed version that might drift from what you actually have.

## New files - copy these in directly
```
organizations/models.py                                    (full replacement - it's short)
organizations/migrations/0006_organization_location_contact.py
accounts/models/task.py
accounts/migrations/0008_task.py
templates/accounts/employee_edit.html
templates/accounts/employee_password_reset_success.html
templates/accounts/my_tasks.html
templates/core/onboarding/step_6.html
```

## accounts/models/__init__.py - add Task to both places
```python
from .task import Task
```
and add `"Task"` to the `__all__` list.

## accounts/forms.py

**SignupForm** - add these two fields (alongside your existing `full_name`,
`business_name`, `terms`):
```python
    business_type = forms.ChoiceField(choices=Organization.BUSINESS_TYPES, label="Business type")
    phone_number = forms.CharField(max_length=20, required=False, label="Phone number")
```
Add this validator method:
```python
    def clean_phone_number(self):
        number = self.cleaned_data.get("phone_number", "").strip()
        if number and PhoneNumber.objects.filter(number=number).exists():
            raise forms.ValidationError("An account with this phone number already exists.")
        return number
```
In `save()`, after `user.save()` and before creating the Organization, add:
```python
        if self.cleaned_data.get("phone_number"):
            PhoneNumber.objects.create(user=user, number=self.cleaned_data["phone_number"], is_primary=True)
```
Change the Organization.objects.create() call's `business_type="retail"` to:
```python
            business_type=self.cleaned_data["business_type"],
```
(Needs `from organizations.models import Organization` at the top if not already imported.)

**Add this new form class** (needs `from .models import EmployeeProfile, Membership` and `from django import forms`):
```python
class EmployeeProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = EmployeeProfile
        fields = ["job_title", "department", "employment_type", "date_joined", "salary", "manager", "status"]
        widgets = {"date_joined": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Membership.objects.filter(organization=organization, is_active=True)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.membership_id)
        self.fields["manager"].queryset = qs
```

## accounts/views.py

Add to imports: `EmployeeProfileForm` (from `.forms`), `EmployeeProfile`, `Task` (from `.models`).

Append these four view classes at the end of the file:
```python
class EmployeeEditView(TeamMixin, View):
    template_name = "accounts/employee_edit.html"

    def _get_membership(self, request, pk):
        return get_object_or_404(Membership, pk=pk, organization=request.organization)

    def get(self, request, pk):
        membership = self._get_membership(request, pk)
        profile, _ = EmployeeProfile.objects.get_or_create(membership=membership)
        form = EmployeeProfileForm(instance=profile, organization=request.organization)
        return render(request, self.template_name, {"membership": membership, "form": form})

    def post(self, request, pk):
        membership = self._get_membership(request, pk)
        profile, _ = EmployeeProfile.objects.get_or_create(membership=membership)
        form = EmployeeProfileForm(request.POST, instance=profile, organization=request.organization)
        if form.is_valid():
            form.save()
            messages.success(request, f"Updated {membership.user.username}'s details.")
            return redirect("team_list")
        return render(request, self.template_name, {"membership": membership, "form": form})


class ResetEmployeePasswordView(TeamMixin, SubscriptionWriteRequiredMixin, View):
    def post(self, request, pk):
        membership = get_object_or_404(Membership, pk=pk, organization=request.organization)
        if membership.user_id == request.user.id:
            messages.error(request, "You can't reset your own password here - use Change Password in Settings.")
            return redirect("team_list")

        from django.utils.crypto import get_random_string

        temp_password = get_random_string(
            length=12, allowed_chars="abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789",
        )
        membership.user.set_password(temp_password)
        membership.user.must_change_password = True
        membership.user.save(update_fields=["password", "must_change_password"])

        request.session["reset_username"] = membership.user.username
        request.session["reset_password"] = temp_password
        return redirect("employee_password_reset_success")


class EmployeePasswordResetSuccessView(TeamMixin, View):
    def get(self, request):
        username = request.session.pop("reset_username", None)
        password = request.session.pop("reset_password", None)
        if not username:
            return redirect("team_list")
        return render(
            request, "accounts/employee_password_reset_success.html",
            {"username": username, "password": password},
        )


class MyTasksView(LoginRequiredMixin, View):
    template_name = "accounts/my_tasks.html"

    def get(self, request):
        if not request.membership:
            return redirect("home")
        tasks = request.membership.tasks.all()
        return render(request, self.template_name, {"tasks": tasks})

    def post(self, request):
        if not request.membership:
            return redirect("home")
        task = get_object_or_404(Task, pk=request.POST.get("task_id"), membership=request.membership)
        task.is_completed = not task.is_completed
        task.completed_at = timezone.now() if task.is_completed else None
        task.save(update_fields=["is_completed", "completed_at"])
        return redirect("my_tasks")
```
(`timezone` needs `from django.utils import timezone` - almost certainly already imported for the email-verification work from earlier.)

## accounts/urls.py - add these four lines
```python
    path("team/<int:pk>/edit/", views.EmployeeEditView.as_view(), name="employee_edit"),
    path("team/<int:pk>/reset-password/", views.ResetEmployeePasswordView.as_view(), name="reset_employee_password"),
    path("team/reset-password/success/", views.EmployeePasswordResetSuccessView.as_view(), name="employee_password_reset_success"),
    path("my-tasks/", views.MyTasksView.as_view(), name="my_tasks"),
```

## accounts/admin.py - register Task
```python
from .models import Task  # add to existing import

@admin.register(Task)
class TaskAdmin(ModelAdmin):
    list_display = ("title", "membership", "due_date", "is_completed")
    list_filter = ("is_completed",)
    autocomplete_fields = ("membership",)
```

## templates/accounts/team_list.html - add two buttons next to "Deactivate"

In the **desktop table's** action `<td>`, right before the existing toggle-active `<form>`:
```html
<a href="{% url 'employee_edit' membership.pk %}" class="btn btn-outline-primary btn-sm">Edit</a>
<form method="post" action="{% url 'reset_employee_password' membership.pk %}" style="display:inline;">
    {% csrf_token %}
    <button type="submit" class="btn btn-outline-warning btn-sm">Reset Password</button>
</form>
```

In the **mobile card** layout, add under the role `<small>`:
```html
<div><a href="{% url 'employee_edit' membership.pk %}" class="small">Edit details</a></div>
```

## templates/accounts/signup.html - add two fields

Right before the existing "Your email" field block, add matching blocks for
`form.business_type` and `form.phone_number` (same structure as the
existing `form.business_name` block - label + field + error div).

## templates/core/onboarding/step_1.html - sync the option list

Replace the `<select id="id_business_type">` options with:
```html
<option value="retail">Retail / Shop</option>
<option value="wholesale">Wholesale / Distribution</option>
<option value="manufacturing">Manufacturing</option>
<option value="restaurant">Restaurant / Food</option>
<option value="hospitality">Hotel / Guesthouse</option>
<option value="salon">Salon / Barbershop</option>
<option value="workshop">Workshop / Repair</option>
<option value="services">Professional Services</option>
<option value="education">School / Training</option>
<option value="agriculture">Agriculture / Agribusiness</option>
<option value="other">Other</option>
```

## core/views.py - OnboardingStepView (FR-02, Iteration 2)

Add a step 6 branch:
```python
        elif step == 6:
            org.address = request.POST.get("address", "").strip()
            org.city = request.POST.get("city", "").strip()
            org.phone_number = request.POST.get("phone_number", "").strip()
            currency = request.POST.get("currency", "MWK")
            if currency in ("MWK", "USD"):
                org.currency = currency
            org.save(update_fields=["address", "city", "phone_number", "currency"])
```
And change every `if next_step > 5:` (or wherever the wizard currently caps
out) to `if next_step > 6:`, and the `elif step == 5:` branch's
`return redirect("home")` should move to `elif step == 6:` instead, since
step 5 ("You're all set!") now needs a "Next" button forward to step 6
rather than finishing the wizard. Simplest fix: in `templates/core/onboarding/step_5.html`,
change the "Go to Dashboard" button to link to
`{% url 'onboarding_step' step=6 %}` instead of `{% url 'home' %}`.

## What FR-02 still doesn't cover

CSV import of existing products/customers/stock - the original gap-analysis
doc itself suggested skipping this for MVP or adding a placeholder. Not
built here either; flagging it as the one still-open item in FR-02.
