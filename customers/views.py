# customers/views.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView

from core.permissions import OrganizationMixin, RoleRequiredMixin
from .models import Customer, Payment
from .forms import PaymentForm

class CustomerMixin(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin):
    allowed_roles = ["owner", "accountant"]

    def get_queryset(self):
        return Customer.objects.filter(organization=self.get_organization()).order_by("name")

class CustomerListView(CustomerMixin, ListView):
    template_name = "customers/customer_list.html"
    context_object_name = "customers"
    paginate_by = 20

class CustomerDetailView(CustomerMixin, DetailView):
    model = Customer
    template_name = "customers/customer_detail.html"
    context_object_name = "customer"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get sales for this customer
        context["sales"] = self.object.sales.filter(
            organization=self.get_organization()
        ).order_by("-created_at")
        # Get payments
        context["payments"] = self.object.payments.filter(
            organization=self.get_organization()
        ).order_by("-created_at")
        return context

class PaymentCreateView(CustomerMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = "customers/payment_form.html"
    success_url = reverse_lazy("customer_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    def form_valid(self, form):
        form.instance.organization = self.get_organization()
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        # Update customer's balance
        customer = form.instance.customer
        customer.outstanding_balance -= form.instance.amount
        customer.save(update_fields=["outstanding_balance"])
        messages.success(self.request, f"Payment of MK{form.instance.amount} recorded for {customer.name}.")
        return response