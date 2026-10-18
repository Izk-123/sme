"""
Expense views — list, create, delete.

The delete view is a hard delete, which silently changes past profit
and past supplier balances. A "void with a reason" flow would be
safer; for now the confirm template spells out that the action cannot
be undone, and the success message fires reliably (Django 4+ posts
DeleteView through form_valid, not delete()).
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView

from core.permissions import (
    OrganizationMixin,
    RoleRequiredMixin,
    SubscriptionWriteRequiredMixin,
)

from .forms import ExpenseForm
from .models import Expense


class ExpenseMixin(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin):
    allowed_roles = ["owner", "accountant"]

    def get_queryset(self):
        return (
            Expense.objects
            .filter(organization=self.get_organization())
            .select_related("category", "supplier")
            .order_by("-date")
        )


class ExpenseListView(ExpenseMixin, ListView):
    template_name = "expenses/expense_list.html"
    context_object_name = "expenses"
    paginate_by = 20


class ExpenseCreateView(ExpenseMixin, SubscriptionWriteRequiredMixin, CreateView):
    template_name = "expenses/expense_form.html"
    form_class = ExpenseForm
    success_url = reverse_lazy("expense_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    def form_valid(self, form):
        form.instance.organization = self.get_organization()
        form.instance.created_by = self.request.user
        messages.success(self.request, "Expense recorded successfully.")
        return super().form_valid(form)


class ExpenseDeleteView(ExpenseMixin, SubscriptionWriteRequiredMixin, DeleteView):
    model = Expense
    template_name = "expenses/expense_confirm_delete.html"
    success_url = reverse_lazy("expense_list")

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.organization != self.get_organization():
            raise Http404
        return obj

    def form_valid(self, form):
        # Django 4+ posts DeleteView through form_valid(); the old
        # delete() override never fired, so the success message was
        # silently dropped. Doing it here makes the toast appear.
        messages.success(self.request, "Expense deleted.")
        return super().form_valid(form)