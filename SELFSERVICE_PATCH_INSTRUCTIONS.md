# FR-05 Self-Service Portal patch - apply on top of the previous gap-analysis patch

Same approach as last time: brand-new files (in this zip, under
accounts/models/, accounts/migrations/, templates/) are safe to drop in
directly. Everything below is an exact snippet to add to files you
already have.

## Consolidation decision

The proposal suggested a brand-new `/selfservice/` page. This project
already has a `/settings/` page (Profile/Security/etc.) and, from the
previous patch, a `/my-tasks/` page. Rather than add a *third* "my
stuff" page, `/selfservice/` becomes the one home for tasks, expense
claims, requests, attendance, and performance - Profile/Password stay
on Settings (the portal just links there). `/my-tasks/` now redirects
to `/selfservice/` instead of duplicating it.

`templates/accounts/my_tasks.html` from the previous patch is now
unused - safe to delete, or leave in place, it just won't be referenced
by any view anymore.

## accounts/forms.py - add these two forms

```python
class ExpenseRequestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ExpenseRequest
        fields = ["amount", "category", "description", "receipt"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
    # No manual `class: form-control` widget attrs needed - BootstrapFormMixin
    # already adds them (the original proposal duplicated that by hand).


class EmployeeRequestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = EmployeeRequest
        fields = ["request_type", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
```
Needs `from .models import ExpenseRequest, EmployeeRequest` added to the
existing models import.

## accounts/views.py

Add to imports: `ExpenseRequestForm, EmployeeRequestForm` (from `.forms`),
`ExpenseRequest, EmployeeRequest, AttendanceRecord` (from `.models`).

**Replace `MyTasksView` and its URL** with a redirect (the portal now
covers this):
```python
class MyTasksRedirectView(LoginRequiredMixin, RedirectView):
    pattern_name = "selfservice_portal"
```
(`RedirectView` should already be imported from `django.views.generic` -
it was used for `ProfileRedirectView` earlier.)

**Add the portal view** - note the `try/except` around performance
stats: `Sale.created_by` may not exist yet (see the optional sales
migration below), so this degrades to "not tracked yet" instead of a
500 if you haven't applied it.
```python
class SelfServicePortalView(LoginRequiredMixin, View):
    template_name = "accounts/selfservice/portal.html"

    def get(self, request):
        membership = request.membership
        if not membership:
            messages.error(request, "You are not associated with a business.")
            return redirect("home")
        return self._render(request, membership)

    def post(self, request):
        membership = request.membership
        if not membership:
            return redirect("home")

        if request.subscription and not request.subscription.can_write:
            messages.error(request, "Your subscription needs renewing before you can submit new records.")
            return redirect("subscription_detail")

        form_name = request.POST.get("form_name")
        if form_name == "expense":
            form = ExpenseRequestForm(request.POST, request.FILES)
            if form.is_valid():
                expense = form.save(commit=False)
                expense.membership = membership
                expense.save()
                messages.success(request, "Expense claim submitted.")
        elif form_name == "request":
            form = EmployeeRequestForm(request.POST)
            if form.is_valid():
                req = form.save(commit=False)
                req.membership = membership
                req.save()
                messages.success(request, "Request submitted.")
        return redirect("selfservice_portal")

    def _render(self, request, membership):
        from django.db.models import Sum
        from django.utils import timezone

        month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        performance_available = False
        sales_count = 0
        sales_amount = 0
        try:
            sales = membership.user.sales_created.filter(
                organization=request.organization, created_at__gte=month_start,
            )
            sales_count = sales.count()
            sales_amount = sales.aggregate(total=Sum("total"))["total"] or 0
            performance_available = True
        except AttributeError:
            pass

        return render(request, self.template_name, {
            "membership": membership,
            "profile": request.user.profile,
            "tasks": membership.tasks.all(),
            "expense_requests": membership.expense_requests.all(),
            "general_requests": membership.requests.all(),
            "attendance": membership.attendance_records.all()[:10],
            "performance_available": performance_available,
            "sales_count": sales_count,
            "sales_amount": sales_amount,
            "expense_form": ExpenseRequestForm(),
            "request_form": EmployeeRequestForm(),
        })


class TaskCompleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        membership = request.membership
        if not membership:
            return redirect("home")
        task = get_object_or_404(Task, pk=pk, membership=membership)
        task.is_completed = not task.is_completed
        task.completed_at = timezone.now() if task.is_completed else None
        task.save(update_fields=["is_completed", "completed_at"])
        return redirect("selfservice_portal")


class TeamRequestsView(TeamMixin, View):
    template_name = "accounts/team_requests.html"

    def get(self, request):
        return render(request, self.template_name, {
            "expense_requests": ExpenseRequest.objects.filter(
                membership__organization=request.organization,
            ).select_related("membership__user"),
            "employee_requests": EmployeeRequest.objects.filter(
                membership__organization=request.organization,
            ).select_related("membership__user"),
        })


class ReviewExpenseRequestView(TeamMixin, View):
    def post(self, request, pk, action):
        expense = get_object_or_404(ExpenseRequest, pk=pk, membership__organization=request.organization)
        if action in ("approve", "reject") and expense.status == "pending":
            expense.status = "approved" if action == "approve" else "rejected"
            expense.reviewed_by = request.user
            expense.reviewed_at = timezone.now()
            expense.save(update_fields=["status", "reviewed_by", "reviewed_at"])
            messages.success(request, f"Expense claim {expense.status}.")
        return redirect("team_requests")


class ReviewEmployeeRequestView(TeamMixin, View):
    def post(self, request, pk, action):
        req = get_object_or_404(EmployeeRequest, pk=pk, membership__organization=request.organization)
        if action in ("approve", "reject") and req.status == "pending":
            req.status = "approved" if action == "approve" else "rejected"
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save(update_fields=["status", "reviewed_by", "reviewed_at"])
            messages.success(request, f"Request {req.status}.")
        return redirect("team_requests")
```

**Remove** the old `MyTasksView` class (superseded by `SelfServicePortalView`
+ `TaskCompleteView` above).

## accounts/urls.py

Replace the `my-tasks/` line from the previous patch with:
```python
    path("my-tasks/", views.MyTasksRedirectView.as_view(), name="my_tasks"),
    path("selfservice/", views.SelfServicePortalView.as_view(), name="selfservice_portal"),
    path("selfservice/tasks/<int:pk>/complete/", views.TaskCompleteView.as_view(), name="complete_task"),
    path("team/requests/", views.TeamRequestsView.as_view(), name="team_requests"),
    path("team/requests/expense/<int:pk>/<str:action>/", views.ReviewExpenseRequestView.as_view(), name="review_expense_request"),
    path("team/requests/employee/<int:pk>/<str:action>/", views.ReviewEmployeeRequestView.as_view(), name="review_employee_request"),
```

## accounts/admin.py - register the three new models

```python
from .models import ExpenseRequest, EmployeeRequest, AttendanceRecord  # add to existing import

@admin.register(ExpenseRequest)
class ExpenseRequestAdmin(ModelAdmin):
    list_display = ("membership", "amount", "category", "status", "created_at")
    list_filter = ("status",)

@admin.register(EmployeeRequest)
class EmployeeRequestAdmin(ModelAdmin):
    list_display = ("membership", "request_type", "status", "created_at")
    list_filter = ("status", "request_type")

@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(ModelAdmin):
    list_display = ("membership", "date", "status", "check_in", "check_out")
    list_filter = ("status",)
    autocomplete_fields = ("membership",)
```

## base.html - add nav links

In the sidebar's "System" section (near Team/Security):
```html
<li class="nav-item">
  <a class="nav-link collapsed" href="{% url 'selfservice_portal' %}">
    <i class="bi bi-person-workspace"></i>
    <span>My Portal</span>
  </a>
</li>
<li class="nav-item">
  <a class="nav-link collapsed" href="{% url 'team_requests' %}">
    <i class="bi bi-inbox"></i>
    <span>Requests</span>
  </a>
</li>
```

## Optional: Sale.created_by (needed for the performance snapshot)

Add to `sales/models.py`'s `Sale` model:
```python
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_created",
    )
```
(needs `from django.conf import settings` in that file). Then wherever
`Sale.objects.create(...)` is called in `CreateSaleView`, add
`created_by=request.user`. Migration:
```python
from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("sales", "FIX_ME_your_latest_sales_migration"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(
            model_name="sale", name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                     related_name="sales_created", to=settings.AUTH_USER_MODEL),
        ),
    ]
```
Not applying this is fine - `SelfServicePortalView` degrades gracefully.

## What's still open from the FR-05 list

- **Attendance**: view-only - no clock-in/out UI (the FR wording says
  "view attendance," not "record" it).
- **Notifications**: already covered by the WebSocket/notify_user() work
  from earlier, not duplicated here.
- Approving an ExpenseRequest does **not** automatically create a real
  `expenses.Expense` record - manual follow-up for the owner for now.
