"""
Supplier views — list, detail, create, edit, payments.

Multi-tenancy rule that applies everywhere here:
    every ORM lookup that takes an ID from the request filters by the
    current organization. `Supplier.objects.get(pk=...)` alone is a
    cross-tenant bug — see the tenant-isolation test.
"""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
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
    allowed_roles = ["owner", "accountant"]

    def get_queryset(self):
        # Base queryset: all suppliers for this org, active AND inactive.
        # The list view narrows this (hides inactive by default).
        # Pickers in forms filter is_active=True on their own.
        return (
            Supplier.objects
            .filter(organization=self.get_organization())
            .order_by("name")
        )


# ---------------------------------------------------------------------------
# Supplier list / detail / create / update
# ---------------------------------------------------------------------------

class SupplierListView(SupplierMixin, ListView):
    template_name = "suppliers/supplier_list.html"
    context_object_name = "suppliers"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()

        # Inactive hidden by default; "?show=all" reveals them.
        if self.request.GET.get("show") != "all":
            qs = qs.filter(is_active=True)

        # Free-text search across the fields users glance at.
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(phone__icontains=q)
                | Q(email__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["show_inactive"] = self.request.GET.get("show") == "all"
        context["search_query"] = (self.request.GET.get("q") or "").strip()
        return context


class SupplierDetailView(SupplierMixin, DetailView):
    model = Supplier
    template_name = "suppliers/supplier_detail.html"
    context_object_name = "supplier"

    PURCHASES_PER_PAGE = 20
    EXPENSES_PER_PAGE = 20
    PAYMENTS_PER_PAGE = 20

    def get_queryset(self):
        return Supplier.objects.filter(organization=self.get_organization())

    def _paginate(self, queryset, param_name, per_page):
        """Small helper so each section paginates independently."""
        paginator = Paginator(queryset, per_page)
        page = self.request.GET.get(param_name, 1)
        try:
            return paginator.page(page)
        except PageNotAnInteger:
            return paginator.page(1)
        except EmptyPage:
            return paginator.page(paginator.num_pages)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        purchases_qs = (
            self.object.stock_movements
            .filter(movement_type="purchase")
            .select_related("product")
            .order_by("-created_at")
        )
        expenses_qs = (
            self.object.expenses
            .select_related("category")
            .order_by("-date", "-id")
        )
        payments_qs = (
            self.object.payments
            .order_by("-date", "-id")
        )

        context["purchases"] = self._paginate(
            purchases_qs, "purchases_page", self.PURCHASES_PER_PAGE,
        )
        context["expenses"] = self._paginate(
            expenses_qs, "expenses_page", self.EXPENSES_PER_PAGE,
        )
        context["payments"] = self._paginate(
            payments_qs, "payments_page", self.PAYMENTS_PER_PAGE,
        )

        # Totals are computed in SQL over the FULL queryset (not just
        # the current page) so the strip at the top of the page keeps
        # reflecting the whole history.
        #
        # IMPORTANT: these expressions must match
        # Supplier.update_balance() EXACTLY, or the detail page's
        # "Total billed" and the "You owe" figure will disagree.
        line_cost = Coalesce(
            F("unit_cost"),
            F("product__cost_price"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
        stock_total = (
            purchases_qs.aggregate(
                total=Sum(ExpressionWrapper(
                    F("quantity") * line_cost,
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                ))
            )["total"]
            or Decimal("0.00")
        )
        # Same filter update_balance() uses: only on_credit expenses
        # count as owed. Cash-paid expenses belong to the cash report,
        # not to this supplier's balance.
        expense_total = (
            expenses_qs.filter(on_credit=True)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        payments_total = (
            payments_qs.aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        context["stock_total"] = stock_total
        context["expense_total"] = expense_total
        context["payments_total"] = payments_total
        context["combined_total"] = stock_total + expense_total

        # True when outstanding_balance < 0 — the UI labels it
        # "You have credit with this supplier" instead of "You owe".
        context["is_credit"] = self.object.outstanding_balance < 0
        return context


class SupplierCreateView(SupplierMixin, SubscriptionWriteRequiredMixin, CreateView):
    model = Supplier
    form_class = SupplierForm
    template_name = "suppliers/supplier_form.html"
    success_url = reverse_lazy("supplier_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    def form_valid(self, form):
        form.instance.organization = self.get_organization()
        response = super().form_valid(form)
        # Push any opening_balance through update_balance() so the
        # balance the owner sees immediately includes it, without
        # needing a signal on Supplier itself.
        self.object.update_balance()
        messages.success(
            self.request, f'Supplier "{form.instance.name}" added.',
        )
        return response


class SupplierUpdateView(SupplierMixin, SubscriptionWriteRequiredMixin, UpdateView):
    model = Supplier
    form_class = SupplierForm
    template_name = "suppliers/supplier_form.html"

    def get_queryset(self):
        # Intentionally NOT filtering is_active — an inactive supplier
        # is still editable (that's where reactivation happens).
        return Supplier.objects.filter(organization=self.get_organization())

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    def get_success_url(self):
        return reverse_lazy("supplier_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        # A changed opening_balance must flow into the running total
        # right away.
        self.object.update_balance()
        messages.success(
            self.request, f'Supplier "{form.instance.name}" updated.',
        )
        return response


# ---------------------------------------------------------------------------
# Supplier payments
# ---------------------------------------------------------------------------

class SupplierPaymentListView(SupplierMixin, ListView):
    template_name = "suppliers/payment_list.html"
    context_object_name = "payments"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            SupplierPayment.objects
            .filter(organization=self.get_organization())
            .select_related("supplier")
            .order_by("-date", "-id")
        )

        # ?supplier=<pk> filters the ledger to one supplier — the
        # counterpart to the "Record Payment" deep link on the detail
        # page.
        supplier_id = self.request.GET.get("supplier")
        if supplier_id and supplier_id.isdigit():
            qs = qs.filter(supplier_id=supplier_id)

        # Free-text search over reference and supplier name.
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(supplier__name__icontains=q) | Q(reference__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["all_suppliers"] = (
            Supplier.objects
            .filter(organization=self.get_organization())
            .order_by("name")
        )
        context["current_supplier"] = self.request.GET.get("supplier", "")
        context["search_query"] = (self.request.GET.get("q") or "").strip()
        return context


class SupplierPaymentCreateView(SupplierMixin, SubscriptionWriteRequiredMixin, CreateView):
    template_name = "suppliers/payment_form.html"
    form_class = SupplierPaymentForm
    success_url = reverse_lazy("supplier_payment_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        supplier_id = self.request.GET.get("supplier")
        if supplier_id and supplier_id.isdigit():
            initial["supplier"] = supplier_id
        return initial

    def form_valid(self, form):
        form.instance.organization = self.get_organization()
        form.instance.created_by = self.request.user

        # Informational nudge — an overpayment is allowed (refunds and
        # prepayments are real). The supplier's balance going negative
        # means you have credit, and the detail page labels it as such.
        supplier = form.instance.supplier
        amount = form.instance.amount
        if supplier.outstanding_balance >= 0 and amount > supplier.outstanding_balance:
            messages.info(
                self.request,
                f"Payment recorded. {supplier.name}'s balance is now in credit "
                f"(you've paid more than was owed).",
            )
        else:
            messages.success(self.request, "Payment recorded.")
        return super().form_valid(form)