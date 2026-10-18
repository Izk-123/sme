"""
Customer and payment views.

Access control is layered:
    CustomerMixin
      ├── LoginRequiredMixin
      ├── RoleRequiredMixin       — owner / accountant only
      └── OrganizationMixin

Write views add SubscriptionWriteRequiredMixin.

Payment safety
--------------
PaymentCreateView runs inside one transaction, locks the customer
row with select_for_update(), rejects overpayments, recalculates the
balance with update_balance(), and FIFO-allocates the payment across
the customer's open sales (for the ageing report).

Deactivation
------------
Customer uses is_active rather than deletion.
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
from .services import allocate_payment


class CustomerMixin(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin):
    allowed_roles = ["owner", "accountant"]

    def get_queryset(self):
        return (
            Customer.objects
            .filter(organization=self.get_organization())
            .order_by("name")
        )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class CustomerListView(CustomerMixin, ListView):
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
        return Customer.objects.filter(organization=self.get_organization())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.get_organization()
        context["sales"] = (
            self.object.sales.filter(organization=org).order_by("-created_at")
        )
        context["payments"] = (
            self.object.payments.filter(organization=org).order_by("-created_at")
        )
        return context


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class CustomerCreateView(CustomerMixin, SubscriptionWriteRequiredMixin, CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = "customers/customer_form.html"
    success_url = reverse_lazy("customer_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    def form_valid(self, form):
        form.instance.organization = self.get_organization()
        response = super().form_valid(form)
        self.object.update_balance()
        messages.success(self.request, f"Customer “{self.object.name}” added.")
        return response


# ---------------------------------------------------------------------------
# Toggle active
# ---------------------------------------------------------------------------

class CustomerToggleActiveView(CustomerMixin, SubscriptionWriteRequiredMixin, View):
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
                f"“{customer.name}” deactivated. Their history is kept.",
            )
        return redirect("customer_detail", pk=customer.pk)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

class PaymentCreateView(CustomerMixin, SubscriptionWriteRequiredMixin, CreateView):
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
        if customer_id and customer_id.isdigit():
            if Customer.objects.filter(
                pk=customer_id, organization=self.get_organization(),
            ).exists():
                initial["customer"] = customer_id
        return initial

    def get_success_url(self):
        return reverse("customer_detail", args=[self.object.customer_id])

    @transaction.atomic
    def form_valid(self, form):
        org = self.get_organization()

        customer = Customer.objects.select_for_update().get(
            pk=form.cleaned_data["customer"].pk, organization=org,
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

        # FIFO allocation for the ageing report. Idempotent — safe even
        # though the post_save signal may also call it.
        allocate_payment(self.object)

        # Recalculate from source, not -= amount.
        customer.update_balance()

        messages.success(
            self.request,
            f"Payment of MK{form.instance.amount:,.2f} recorded for {customer.name}.",
        )
        return response