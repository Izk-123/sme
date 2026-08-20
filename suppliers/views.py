# suppliers/views.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView

from core.permissions import OrganizationMixin, RoleRequiredMixin
from .models import Supplier

class SupplierMixin(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin):
    allowed_roles = ["owner", "accountant"]

    def get_queryset(self):
        return Supplier.objects.filter(organization=self.get_organization()).order_by("name")

class SupplierListView(SupplierMixin, ListView):
    template_name = "suppliers/supplier_list.html"
    context_object_name = "suppliers"
    paginate_by = 20

class SupplierDetailView(SupplierMixin, DetailView):
    model = Supplier
    template_name = "suppliers/supplier_detail.html"
    context_object_name = "supplier"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get all purchase stock movements linked to this supplier
        context["purchases"] = self.object.stock_movements.filter(
            movement_type="purchase"
        ).select_related("product").order_by("-created_at")
        return context