"""Supplier views — list, detail, create, edit, and payments."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    UpdateView,
)

from core.permissions import (
    OrganizationMixin,
    RoleRequiredMixin,
    SubscriptionWriteRequiredMixin,
)

from .forms import SupplierForm, SupplierPaymentForm
from .models import Supplier, SupplierPayment


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------

class SupplierMixin(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin):
    """
    Common plumbing for every supplier view.

    - LoginRequiredMixin: no anonymous access.
    - RoleRequiredMixin:   only owners / accountants (see allowed_roles).
    - OrganizationMixin:   provides get_organization(); every queryset
                           below is filtered by it, so nothing leaks
                           across tenants.

    The default queryset is the whole org's supplier list; subclasses
    override get_queryset() when they need a narrower scope.
    """

    allowed_roles = ["owner", "accountant"]

    def get_queryset(self):
        return (
            Supplier.objects
            .filter(organization=self.get_organization())
            .order_by("name")
        )


# ---------------------------------------------------------------------------
# Supplier CRUD
# ---------------------------------------------------------------------------

class SupplierListView(SupplierMixin, ListView):
    template_name = "suppliers/supplier_list.html"
    context_object_name = "suppliers"
    paginate_by = 20


class SupplierDetailView(SupplierMixin, DetailView):
    model = Supplier
    template_name = "suppliers/supplier_detail.html"
    context_object_name = "supplier"

    def get_queryset(self):
        # Scope to org so /suppliers/<pk>/ can't leak cross-tenant.
        return Supplier.objects.filter(organization=self.get_organization())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # ---- Purchases (stock movements of type 'purchase') -------------
        purchases = (
            self.object.stock_movements
            .filter(movement_type="purchase")
            .select_related("product")
            .order_by("-created_at")
        )
        context["purchases"] = purchases

        # ---- Expenses (services / fees billed by this supplier) ---------
        expenses = (
            self.object.expenses
            .select_related("category")
            .order_by("-date")
        )
        context["expenses"] = expenses

        # ---- Stock total -------------------------------------------------
        # MUST use the same expression as Supplier.update_balance(),
        # otherwise the "combined_total" shown here disagrees with the
        # outstanding_balance shown on the list page:
        #     unit_cost = cost_price, falling back to price when blank.
        #
        # Done in SQL (one aggregate) instead of a Python for-loop, so a
        # supplier with 10k purchase rows doesn't drag the page.
        unit_cost = Coalesce(
            F("product__cost_price"),
            F("product__price"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
        stock_total = (
            purchases.aggregate(
                total=Sum(
                    ExpressionWrapper(
                        F("quantity") * unit_cost,
                        output_field=DecimalField(max_digits=14, decimal_places=2),
                    )
                )
            )["total"]
            or Decimal("0.00")
        )

        # ---- Expense total ----------------------------------------------
        expense_total = (
            expenses.aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        context["stock_total"] = stock_total
        context["expense_total"] = expense_total
        context["combined_total"] = stock_total + expense_total
        return context


class SupplierCreateView(SupplierMixin, SubscriptionWriteRequiredMixin, CreateView):
    """
    Add a supplier.

    Writes are gated by SubscriptionWriteRequiredMixin — the list / detail
    pages stay readable even on an expired plan, but creating a record
    requires an active subscription.
    """

    model = Supplier
    form_class = SupplierForm
    template_name = "suppliers/supplier_form.html"
    success_url = reverse_lazy("supplier_list")

    def form_valid(self, form):
        # Stamp org from the session, never from the form. This is the
        # tenant-isolation boundary for creates.
        form.instance.organization = self.get_organization()
        messages.success(self.request, f'Supplier "{form.instance.name}" added.')
        return super().form_valid(form)


class SupplierUpdateView(SupplierMixin, SubscriptionWriteRequiredMixin, UpdateView):
    """Edit an existing supplier. Scoped to the caller's organization."""

    model = Supplier
    form_class = SupplierForm
    template_name = "suppliers/supplier_form.html"

    def get_queryset(self):
        return Supplier.objects.filter(organization=self.get_organization())

    def get_success_url(self):
        # Land on the detail page so the user sees their edit reflected.
        return reverse_lazy("supplier_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, f'Supplier "{form.instance.name}" updated.')
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Supplier payments
# ---------------------------------------------------------------------------

class SupplierPaymentListView(SupplierMixin, ListView):
    template_name = "suppliers/payment_list.html"
    context_object_name = "payments"
    paginate_by = 20

    def get_queryset(self):
        return (
            SupplierPayment.objects
            .filter(organization=self.get_organization())
            .select_related("supplier")
            .order_by("-date", "-id")
        )


class SupplierPaymentCreateView(SupplierMixin, SubscriptionWriteRequiredMixin, CreateView):
    template_name = "suppliers/payment_form.html"
    form_class = SupplierPaymentForm
    success_url = reverse_lazy("supplier_payment_list")

    def get_form_kwargs(self):
        # Hand the form its org so the supplier dropdown is scoped.
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    def get_initial(self):
        # Deep-link support: /suppliers/payments/add/?supplier=<pk>
        # pre-selects the supplier. Bounded to an integer string here;
        # the form's queryset filter rejects a foreign or bogus id anyway.
        initial = super().get_initial()
        supplier_id = self.request.GET.get("supplier")
        if supplier_id:
            initial["supplier"] = supplier_id
        return initial

    def form_valid(self, form):
        form.instance.organization = self.get_organization()
        form.instance.created_by = self.request.user
        messages.success(self.request, "Payment recorded.")
        return super().form_valid(form)