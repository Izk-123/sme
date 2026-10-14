"""
Customer and payment views.

Access control is layered:

    CustomerMixin
      ├── LoginRequiredMixin
      ├── RoleRequiredMixin       — owner / accountant only
      └── OrganizationMixin

Write views add SubscriptionWriteRequiredMixin.

Query scoping
-------------
`CustomerMixin.get_queryset()` filters by organization for ListView.
DetailView bypasses it, so CustomerDetailView re-declares it — this closes
a real cross-tenant read that would otherwise be one integer guess away.

Payment safety
--------------
PaymentCreateView runs inside one transaction, locks the customer row with
select_for_update(), rejects overpayments, and recalculates the balance
with update_balance() rather than mutating it in place. Balance and
payments therefore cannot drift apart, even under concurrent requests.

Deactivation
------------
Customer uses `is_active` rather than deletion. Sales and Payments FK to
Customer with CASCADE, so deleting a customer would erase their entire
debt history and turn their credit sales into anonymous "Walk-in" rows.
Deactivation keeps the record intact but hides them from new sales and
payment forms.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView

from core.permissions import (
    OrganizationMixin,
    RoleRequiredMixin,
    SubscriptionWriteRequiredMixin,
)
from .forms import CustomerForm, PaymentForm
from .models import Customer, Payment


class CustomerMixin(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin):
    """
    Shared base for every customers view.

    allowed_roles is intentionally narrow: cashiers record sales, they
    don't manage the customer directory or take payments at the till.
    Add "cashier" here if that changes.
    """

    allowed_roles = ["owner", "accountant"]

    def get_queryset(self):
        """
        Org-scoped, alphabetically ordered customer queryset.

        Used by ListView. DetailView overrides this (see below) because
        it does not call get_queryset() on its own.
        """
        return (
            Customer.objects
            .filter(organization=self.get_organization())
            .order_by("name")
        )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class CustomerListView(CustomerMixin, ListView):
    """
    List customers for the current organization.

    Active customers are shown by default. `?show=all` reveals deactivated
    ones — used by the "Show inactive" link in the template so an owner
    can still find and reactivate someone they previously turned off.
    """

    template_name = "customers/customer_list.html"
    context_object_name = "customers"
    paginate_by = 20

    def get_queryset(self):
        qs = Customer.objects.filter(organization=self.get_organization())
        if self.request.GET.get("show") != "all":
            qs = qs.filter(is_active=True)
        return qs.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["showing_all"] = self.request.GET.get("show") == "all"

        # Count of inactive customers, so the "Show inactive" link can say
        # "Show 3 inactive" and only appear when there's something to show.
        context["inactive_count"] = Customer.objects.filter(
            organization=self.get_organization(), is_active=False
        ).count()
        return context


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

class CustomerDetailView(CustomerMixin, DetailView):
    template_name = "customers/customer_detail.html"
    context_object_name = "customer"

    def get_queryset(self):
        """
        DetailView does not use CustomerMixin.get_queryset() unless we
        redeclare it here. Without this, /customers/<pk>/ serves any
        tenant's customer to any authenticated owner.
        """
        return Customer.objects.filter(
            organization=self.get_organization()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.get_organization()

        # Filtering by organization keeps the contract explicit: even if
        # a Customer somehow ended up cross-linked to another org's sale
        # (via a data migration bug, a manual admin edit, or a future
        # schema change), this page still won't show it.
        context["sales"] = (
            self.object.sales
            .filter(organization=org)
            .order_by("-created_at")
        )
        context["payments"] = (
            self.object.payments
            .filter(organization=org)
            .order_by("-created_at")
        )
        return context


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class CustomerCreateView(CustomerMixin, SubscriptionWriteRequiredMixin, CreateView):
    """
    Add a customer to the current organization.

    MRO note: SubscriptionWriteRequiredMixin must sit after CustomerMixin
    so that request.organization is guaranteed to exist before the
    subscription check runs.
    """

    model = Customer
    form_class = CustomerForm
    template_name = "customers/customer_form.html"
    success_url = reverse_lazy("customer_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    def form_valid(self, form):
        # organization is set on the *instance*, not the form, so a POST
        # that injects an `organization` field in the body is ignored.
        form.instance.organization = self.get_organization()
        response = super().form_valid(form)

        # Compute outstanding_balance from opening_balance + any existing
        # sales and payments. Without this call, a customer created with
        # an opening balance would show 0 in the list.
        self.object.update_balance()

        messages.success(
            self.request,
            f"Customer “{self.object.name}” added.",
        )
        return response


# ---------------------------------------------------------------------------
# Activate / deactivate
# ---------------------------------------------------------------------------

class CustomerToggleActiveView(CustomerMixin, SubscriptionWriteRequiredMixin, View):
    """
    Flip Customer.is_active and return to the detail page.

    POST-only. A GET link would be CSRF-vulnerable and could fire from
    a prefetcher or an embedded <img> tag.
    """

    def post(self, request, pk):
        customer = get_object_or_404(
            Customer, pk=pk, organization=self.get_organization()
        )
        customer.is_active = not customer.is_active
        customer.save(update_fields=["is_active"])

        if customer.is_active:
            messages.success(request, f"“{customer.name}” reactivated.")
        else:
            messages.success(
                request,
                f"“{customer.name}” deactivated. Their history is kept, "
                f"but they won't appear in new sales or payment forms.",
            )
        return redirect("customer_detail", pk=customer.pk)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

class PaymentCreateView(CustomerMixin, SubscriptionWriteRequiredMixin, CreateView):
    """
    Record a payment received from a customer.

    Supports an optional ?customer=<pk> query parameter to pre-select the
    customer in the dropdown — used by the "Record Payment" button on
    customer_detail.html so the user doesn't have to re-pick the person
    they were just looking at. The parameter is validated against the
    current organization before being honoured.
    """

    model = Payment
    form_class = PaymentForm
    template_name = "customers/payment_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        customer_id = self.request.GET.get("customer")

        # isdigit() guards against non-numeric junk; the ORM filter that
        # follows is what actually enforces tenancy. A crafted
        # ?customer=<other-org-id> simply resolves to no match and is
        # ignored, rather than leaking whether that ID exists.
        if customer_id and customer_id.isdigit():
            if Customer.objects.filter(
                pk=customer_id,
                organization=self.get_organization(),
            ).exists():
                initial["customer"] = customer_id
        return initial

    def get_success_url(self):
        # Land on the customer's detail page, not the list — the user
        # almost always wants to confirm the balance changed.
        return reverse("customer_detail", args=[self.object.customer_id])

    @transaction.atomic
    def form_valid(self, form):
        org = self.get_organization()

        # Lock the customer row. Two cashiers recording a payment at the
        # same instant would otherwise both read the same starting balance
        # and each write a value that ignores the other's change.
        # select_for_update() is a no-op on SQLite; production runs on
        # PostgreSQL per settings.py, so it applies there.
        customer = Customer.objects.select_for_update().get(
            pk=form.cleaned_data["customer"].pk,
            organization=org,
        )

        balance = customer.calculate_balance()
        if form.cleaned_data["amount"] > balance:
            form.add_error(
                "amount",
                f"This is more than {customer.name} owes (MK{balance:,.2f}).",
            )
            return self.form_invalid(form)

        form.instance.organization = org
        form.instance.created_by = self.request.user
        response = super().form_valid(form)

        # Recalculate from source (opening + credit - payments), not
        # `-= amount`. The two agreed before but only by luck; if a sale
        # was deleted or an opening balance corrected, the incremental
        # version would quietly diverge.
        customer.update_balance()

        messages.success(
            self.request,
            f"Payment of MK{form.instance.amount:,.2f} recorded for {customer.name}.",
        )
        return response