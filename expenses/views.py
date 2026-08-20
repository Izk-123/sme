# expenses/views.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy
from django.http import Http404
from django.views.generic import ListView, CreateView, DeleteView

from core.permissions import OrganizationMixin, RoleRequiredMixin
from .models import Expense, ExpenseCategory
from .forms import ExpenseForm

class ExpenseMixin(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin):
    allowed_roles = ["owner", "accountant"]

    def get_queryset(self):
        return Expense.objects.filter(organization=self.get_organization()).select_related("category").order_by("-date")

class ExpenseListView(ExpenseMixin, ListView):
    template_name = "expenses/expense_list.html"
    context_object_name = "expenses"
    paginate_by = 20

class ExpenseCreateView(ExpenseMixin, CreateView):
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

class ExpenseDeleteView(ExpenseMixin, DeleteView):
    model = Expense
    success_url = reverse_lazy("expense_list")
    template_name = "expenses/expense_confirm_delete.html"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.organization != self.get_organization():
            raise Http404
        return obj

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Expense deleted.")
        return super().delete(request, *args, **kwargs)