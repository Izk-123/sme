"""
Sales and inventory views.

Multi-tenancy rule that applies everywhere in this module:
    every ORM lookup that takes an ID from the request also filters by
    organization. Product.objects.get(pk=...) alone is a cross-tenant bug.

Transactional rule for write views:
    anything that touches Sale, SaleItem, Product.stock_quantity,
    StockMovement, or Customer.outstanding_balance runs inside
    transaction.atomic().
"""
import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render, reverse
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.html import escape
from django.views import View
from django.views.generic import (
    CreateView, DetailView, FormView, ListView, TemplateView, UpdateView,
)

from core.permissions import (
    OrganizationMixin,
    RoleRequiredMixin,
    SubscriptionWriteRequiredMixin,
)
from customers.models import Customer
from suppliers.models import Supplier, SupplierPayment

from .forms import ProductForm, ReceiveStockForm
from .models import Product, Sale, SaleItem, StockMovement


VALID_PAYMENT_METHODS = {code for code, _label in Sale.PAYMENT_METHODS}


class SaleError(Exception):
    """A problem the cashier should see; rolls the sale back."""


def _parse_lines(post):
    """{product_id: qty} with duplicate rows merged so stock is checked once."""
    wanted = defaultdict(int)
    for pid, qty in zip(post.getlist("product"), post.getlist("quantity")):
        pid = (pid or "").strip()
        qty = (qty or "").strip()
        if not pid.isdigit():
            continue
        try:
            q = int(qty)
        except ValueError:
            continue
        if q > 0:
            wanted[int(pid)] += q
    return dict(wanted)


# =============================================================================
# 1. Sale list
# =============================================================================

class SaleListView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, ListView):
    model = Sale
    template_name = "sales/sale_list.html"
    context_object_name = "sales"
    paginate_by = 20
    allowed_roles = ["owner", "cashier", "accountant"]

    def get_queryset(self):
        qs = (
            super().get_queryset()
            .filter(organization=self.get_organization())
            .select_related("customer")
            .order_by("-created_at")
        )

        customer = self.request.GET.get("customer")
        if customer and customer.isdigit():
            qs = qs.filter(customer_id=customer)

        payment = self.request.GET.get("payment")
        if payment in VALID_PAYMENT_METHODS:
            qs = qs.filter(payment_method=payment)

        # Status filter: paid = fully paid; partial = some paid; due =
        # anything with an outstanding amount.
        status = self.request.GET.get("status")
        if status == "paid":
            qs = qs.filter(amount_paid__gte=F("total"))
        elif status == "due":
            qs = qs.filter(amount_paid__lt=F("total"))
        elif status == "partial":
            qs = qs.filter(
                amount_paid__lt=F("total"),
                amount_paid__gt=0,
            )

        date = self.request.GET.get("date")
        if date:
            try:
                timezone.datetime.strptime(date, "%Y-%m-%d")
                qs = qs.filter(created_at__date=date)
            except ValueError:
                pass

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        today = timezone.localdate()

        context["customers"] = Customer.objects.filter(
            organization=organization, is_active=True,
        )
        context["today_sales"] = float(
            Sale.objects.filter(
                organization=organization, created_at__date=today,
            ).aggregate(total=Sum("total"))["total"] or 0
        )
        context["selected_customer"] = self.request.GET.get("customer", "")
        context["selected_payment"] = self.request.GET.get("payment", "")
        context["selected_status"] = self.request.GET.get("status", "")
        context["selected_date"] = self.request.GET.get("date", "")
        return context


# =============================================================================
# 2. Record sale (form shell)
# =============================================================================

class RecordSaleView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    allowed_roles = ["owner", "cashier"]
    template_name = "sales/record_sale.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        context["products"] = Product.objects.filter(organization=organization)
        context["customers"] = Customer.objects.filter(
            organization=organization, is_active=True,
        )
        context["barcode_enabled"] = bool(
            self.request.subscription
            and self.request.subscription.has_feature("barcode")
        )
        # Fresh token per form render. The POST echoes it back; a
        # double-submit fails on Sale.submission_token's unique index.
        context["submission_token"] = uuid.uuid4().hex
        return context


# =============================================================================
# 3. HTMX helpers
# =============================================================================

class AddItemRowView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    allowed_roles = ["owner", "cashier"]
    template_name = "sales/_item_row.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["products"] = Product.objects.filter(
            organization=self.get_organization(),
        )
        return context


class RemoveItemRowView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    allowed_roles = ["owner", "cashier"]

    def delete(self, request, *args, **kwargs):
        return HttpResponse("")

    def post(self, request, *args, **kwargs):
        return self.delete(request, *args, **kwargs)


class CalculateTotalsView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    allowed_roles = ["owner", "cashier"]

    def post(self, request, *args, **kwargs):
        wanted = _parse_lines(request.POST)
        prices = dict(
            Product.objects
            .filter(organization=self.get_organization(), pk__in=wanted.keys())
            .values_list("pk", "price")
        )
        total = sum(
            (prices[pk] * qty for pk, qty in wanted.items() if pk in prices),
            Decimal("0"),
        )
        return render(request, "sales/_grand_total.html", {"total": total})


# =============================================================================
# 4. Create sale
# =============================================================================

class CreateSaleView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin,
                     SubscriptionWriteRequiredMixin, View):
    """
    Create a sale with every side effect in one transaction.

    Handles all three of:
      * fully paid (amount_paid == total)
      * partial credit (0 < amount_paid < total, customer required)
      * full credit (amount_paid == 0, customer required)

    Idempotency: the client sends a submission_token with the POST.
    A duplicate token means the sale already saved — we redirect to the
    list instead of creating a second row. The same protection is
    enforced at the database level by Sale.submission_token's unique
    index; the IntegrityError path covers a race between the pre-check
    and the insert.
    """

    allowed_roles = ["owner", "cashier"]

    def _error(self, request, message):
        return render(request, "sales/_receipt.html", {"error": message})

    def _redirect_success(self, request):
        if request.headers.get("HX-Request"):
            response = HttpResponse()
            response.headers["HX-Redirect"] = reverse("sale_list")
            return response
        return redirect(reverse("record_sale"))

    def post(self, request, *args, **kwargs):
        org = self.get_organization()

        # ---- Idempotency: refuse duplicate submissions early ----
        token = (request.POST.get("submission_token") or "").strip()[:64] or None
        if token and Sale.objects.filter(submission_token=token).exists():
            return self._redirect_success(request)

        # ---- Payment method ----
        payment_method = request.POST.get("payment_method", "cash")
        if payment_method not in VALID_PAYMENT_METHODS:
            return self._error(request, "Choose a valid payment method.")

        # ---- Customer ----
        customer = None
        customer_id = (request.POST.get("customer") or "").strip()
        if customer_id:
            if not customer_id.isdigit():
                return self._error(request, "Customer not found.")
            customer = Customer.objects.filter(
                pk=customer_id, organization=org, is_active=True,
            ).first()
            if customer is None:
                return self._error(request, "Customer not found.")

        # ---- Items ----
        wanted = _parse_lines(request.POST)
        if not wanted:
            return self._error(
                request, "Add at least one product before completing the sale.",
            )

        # ---- Parse amount_paid and due_date ----
        # amount_paid defaults to the (yet-to-be-computed) total, meaning
        # "fully paid". The user can lower it to record a partial credit
        # sale. If they pick method='credit' we force amount_paid=0.
        raw_amount = (request.POST.get("amount_paid") or "").strip()
        raw_due = (request.POST.get("due_date") or "").strip()

        due_date = None
        if raw_due:
            try:
                due_date = datetime.strptime(raw_due, "%Y-%m-%d").date()
            except ValueError:
                return self._error(request, "Invalid due date.")

        try:
            with transaction.atomic():
                # Lock products.
                products = {
                    p.pk: p
                    for p in Product.objects
                    .select_for_update()
                    .filter(organization=org, pk__in=wanted.keys())
                }
                if len(products) != len(wanted):
                    raise SaleError("One of the products was not found.")

                short = [
                    f"Not enough stock for {p.name} (available: {p.stock_quantity})"
                    for pk, p in products.items()
                    if p.stock_quantity < wanted[pk]
                ]
                if short:
                    raise SaleError(" & ".join(short))

                # Compute total from the database (never from the browser).
                total = Decimal("0")
                for pk, qty in wanted.items():
                    total += products[pk].price * qty
                if total <= 0:
                    raise SaleError(
                        "Sale total is zero. Check that your products have prices set."
                    )

                # Resolve amount_paid against the real total.
                if payment_method == "credit":
                    amount_paid = Decimal("0")
                    if raw_amount:
                        try:
                            typed = Decimal(raw_amount)
                        except InvalidOperation:
                            typed = Decimal("0")
                        if typed > 0:
                            raise SaleError(
                                "You chose Credit but entered a payment. "
                                "To record a partial payment, choose the "
                                "method used for the paid part."
                            )
                else:
                    try:
                        amount_paid = (
                            Decimal(raw_amount) if raw_amount else total
                        )
                    except InvalidOperation:
                        raise SaleError("Amount paid is not a valid number.")
                    if amount_paid == 0:
                        # Cashier picked a real method but paid nothing —
                        # treat it as a full credit sale.
                        payment_method = "credit"

                if amount_paid < 0 or amount_paid > total:
                    raise SaleError(
                        f"Amount paid must be between 0 and MK{total:,.2f}."
                    )

                if amount_paid < total and customer is None:
                    raise SaleError(
                        "Choose a customer for the unpaid part, so the "
                        "debt is recorded."
                    )

                # Create the sale.
                sale = Sale.objects.create(
                    organization=org,
                    customer=customer,
                    payment_method=payment_method,
                    amount_paid=amount_paid,
                    due_date=due_date,
                    submission_token=token,
                    total=total,
                    created_by=request.user,
                )

                # Items, stock, movements.
                for pk, qty in wanted.items():
                    p = products[pk]
                    SaleItem.objects.create(
                        sale=sale, product=p, quantity=qty,
                        unit_price=p.price, unit_cost=p.cost_price,
                    )
                    Product.objects.filter(pk=pk).update(
                        stock_quantity=F("stock_quantity") - qty
                    )
                    StockMovement.objects.create(
                        organization=org, product=p, quantity=-qty,
                        movement_type="sale",
                        reference=f"Sale #{sale.pk}",
                    )

                # Recalculate the customer's balance once, from source.
                if customer is not None:
                    locked = Customer.objects.select_for_update().get(pk=customer.pk)
                    locked.update_balance()

        except IntegrityError:
            # Concurrent duplicate submission: the other request won the
            # unique constraint on submission_token. That request already
            # created the sale — treat this one as a duplicate and go home.
            if token and Sale.objects.filter(submission_token=token).exists():
                return self._redirect_success(request)
            raise
        except SaleError as exc:
            return self._error(request, str(exc))

        return self._redirect_success(request)


# =============================================================================
# 5. Inventory
# =============================================================================

class InventoryListView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, ListView):
    model = Product
    template_name = "sales/inventory_list.html"
    context_object_name = "products"
    paginate_by = 20
    allowed_roles = ["owner", "stock_clerk", "accountant"]

    def get_queryset(self):
        qs = super().get_queryset().filter(organization=self.get_organization())
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(name__icontains=q)
        return qs.order_by("name")


# =============================================================================
# 6. Receive stock  (unchanged from your current file)
# =============================================================================

class ReceiveStockView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin,
                       SubscriptionWriteRequiredMixin, FormView):
    allowed_roles = ["owner", "stock_clerk"]
    template_name = "sales/receive_stock.html"
    form_class = ReceiveStockForm
    success_url = reverse_lazy("inventory_list")

    def get_initial(self):
        initial = super().get_initial()
        sid = self.request.GET.get("supplier", "")
        if sid.isdigit() and Supplier.objects.filter(
            pk=sid, organization=self.get_organization(), is_active=True,
        ).exists():
            initial["supplier"] = sid
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        org = self.get_organization()
        qty = form.cleaned_data["quantity"]
        unit_cost = form.cleaned_data["unit_cost"]
        paid_now = form.cleaned_data.get("paid_now") or Decimal("0")
        supplier = form.cleaned_data.get("supplier")

        product = Product.objects.select_for_update().get(
            pk=form.cleaned_data["product"].pk, organization=org,
        )

        old_qty = max(product.stock_quantity, 0)
        old_cost = product.cost_price
        if old_cost is not None and old_qty > 0:
            product.cost_price = (
                (old_qty * old_cost) + (qty * unit_cost)
            ) / (old_qty + qty)
        else:
            product.cost_price = unit_cost
        product.save(update_fields=["cost_price"])

        Product.objects.filter(pk=product.pk).update(
            stock_quantity=F("stock_quantity") + qty
        )
        product.refresh_from_db(fields=["stock_quantity"])

        StockMovement.objects.create(
            organization=org, product=product, quantity=qty,
            unit_cost=unit_cost, movement_type="purchase",
            supplier=supplier,
            reference=f"Received via {supplier.name if supplier else 'Manual'}",
        )

        if supplier and paid_now > 0:
            SupplierPayment.objects.create(
                organization=org, supplier=supplier,
                date=timezone.localdate(), amount=paid_now, method="cash",
                reference="Paid on delivery", created_by=self.request.user,
            )

        messages.success(
            self.request,
            f"Received {qty} x {product.name}. New stock: {product.stock_quantity}.",
        )
        return super().form_valid(form)


# =============================================================================
# 7. Stock valuation (unchanged)
# =============================================================================

class StockValuationView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    allowed_roles = ["owner", "stock_clerk", "accountant"]
    template_name = "sales/stock_valuation.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        products = list(
            Product.objects.filter(organization=organization).order_by("name")
        )
        total_retail = sum(p.retail_value for p in products)
        total_cost = sum(
            (p.cost_value for p in products if p.cost_value is not None),
            Decimal("0.00"),
        )
        missing_cost_count = sum(1 for p in products if p.cost_price is None)
        context["products"] = products
        context["total_retail_value"] = total_retail
        context["total_cost_value"] = total_cost
        context["product_count"] = len(products)
        context["missing_cost_count"] = missing_cost_count
        return context


# =============================================================================
# 8–9. Barcode scanning (unchanged)
# =============================================================================

class BarcodeScanView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    allowed_roles = ["owner", "cashier"]

    def _code(self, request):
        return (request.GET.get("code") or request.POST.get("barcode") or "").strip()

    def get(self, request):
        if not (request.subscription and request.subscription.has_feature("barcode")):
            return HttpResponse(
                '<div class="alert alert-warning">Barcode scanning needs the Starter plan or above. '
                '<a href="/subscriptions/upgrade/">Upgrade</a></div>'
            )
        code = self._code(request)
        if not code:
            return HttpResponse("")
        product = Product.objects.filter(
            organization=self.get_organization(), barcode=code,
        ).first()
        if not product:
            return HttpResponse(
                f'<div class="alert alert-warning">'
                f'No product found for barcode {escape(code)}</div>'
            )
        return render(request, "sales/_item_row.html", {
            "products": [product], "preselected": product.id,
        })

    def post(self, request):
        return self.get(request)


class BarcodeScanProductView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    allowed_roles = ["owner", "stock_clerk"]

    def _code(self, request):
        return (request.GET.get("code") or request.POST.get("barcode") or "").strip()

    def get(self, request):
        if not (request.subscription and request.subscription.has_feature("barcode")):
            return HttpResponse(
                '<div class="alert alert-warning">Barcode scanning needs the Starter plan or above. '
                '<a href="/subscriptions/upgrade/">Upgrade</a></div>'
            )
        code = self._code(request)
        if not code:
            return render(request, "sales/_product_select.html", {"products": []})
        product = Product.objects.filter(
            organization=self.get_organization(), barcode=code,
        ).first()
        if not product:
            return HttpResponse(
                f'<div class="alert alert-warning">'
                f'No product found for barcode {escape(code)}</div>'
            )
        return render(request, "sales/_product_select.html", {
            "products": [product], "preselected": product.id,
        })

    def post(self, request):
        return self.get(request)


# =============================================================================
# 10–11. Label + product CRUD (unchanged)
# =============================================================================

class ProductLabelView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, DetailView):
    model = Product
    template_name = "sales/product_label.html"
    allowed_roles = ["owner", "stock_clerk"]

    def get_queryset(self):
        return Product.objects.filter(organization=self.get_organization())


class ProductCreateView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin,
                        SubscriptionWriteRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = "sales/product_form.html"
    success_url = reverse_lazy("inventory_list")
    allowed_roles = ["owner", "stock_clerk"]

    def form_valid(self, form):
        form.instance.organization = self.get_organization()
        messages.success(
            self.request, f"Product '{form.instance.name}' added successfully.",
        )
        return super().form_valid(form)


class ProductUpdateView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin,
                        SubscriptionWriteRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = "sales/product_form.html"
    success_url = reverse_lazy("inventory_list")
    allowed_roles = ["owner", "stock_clerk"]

    def get_queryset(self):
        return super().get_queryset().filter(organization=self.get_organization())

    def form_valid(self, form):
        messages.success(
            self.request, f"Product '{form.instance.name}' updated successfully.",
        )
        return super().form_valid(form)