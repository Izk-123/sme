"""
Sales and inventory views.

Multi-tenancy rule that applies everywhere in this module:
    every ORM lookup that takes an ID from the request also filters by
    organization. Product.objects.get(pk=...) alone is a cross-tenant bug.

Transactional rule for write views:
    anything that touches Sale, SaleItem, Product.stock_quantity,
    StockMovement, or Customer.outstanding_balance runs inside
    transaction.atomic(). The old code tried to undo a failed sale by
    hand; that's what atomicity is for.
"""
from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import F, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
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

from .forms import ProductForm, ReceiveStockForm
from .models import Product, Sale, SaleItem, StockMovement


VALID_PAYMENT_METHODS = {code for code, _label in Sale.PAYMENT_METHODS}


class SaleError(Exception):
    """
    A problem the cashier should see, and that should roll the entire
    sale back. Caught in CreateSaleView and rendered into _receipt.html.
    """


def _parse_lines(post):
    """
    Turn the posted product/quantity lists into {product_id: total_qty}.

    Merges duplicate rows so the stock check sees the real total: two
    rows of 6 against a stock of 10 must fail, and the old version let
    it through because each row was checked against stock separately.
    """
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
    """Paginated sales list with optional filters: customer, payment, status, date."""

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

        status = self.request.GET.get("status")
        if status == "paid":
            qs = qs.exclude(payment_method="credit")
        elif status == "due":
            qs = qs.filter(payment_method="credit")

        date = self.request.GET.get("date")
        if date:
            # Bad dates just skip the filter rather than 500.
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
            organization=organization, is_active=True
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
    """Renders the dynamic sale form. Submission is handled by CreateSaleView."""

    allowed_roles = ["owner", "cashier"]
    template_name = "sales/record_sale.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        context["products"] = Product.objects.filter(organization=organization)
        context["customers"] = Customer.objects.filter(
            organization=organization, is_active=True
        )
        context["barcode_enabled"] = bool(
            self.request.subscription
            and self.request.subscription.has_feature("barcode")
        )
        return context


# =============================================================================
# 3. HTMX helpers for the dynamic sale form
# =============================================================================

class AddItemRowView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    allowed_roles = ["owner", "cashier"]
    template_name = "sales/_item_row.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["products"] = Product.objects.filter(
            organization=self.get_organization()
        )
        return context


class RemoveItemRowView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    """Empty response — the client removes the row via hx-swap=outerHTML."""

    allowed_roles = ["owner", "cashier"]

    def delete(self, request, *args, **kwargs):
        return HttpResponse("")

    def post(self, request, *args, **kwargs):
        return self.delete(request, *args, **kwargs)


class CalculateTotalsView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    """
    HTMX: grand total for the rows currently on screen.

    Prices are looked up from the database filtered by organization, so
    another business's prices can't be read by guessing product IDs.
    """

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
# 4. Create sale (the actual transaction)
# =============================================================================

class CreateSaleView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin,
                     SubscriptionWriteRequiredMixin, View):
    """
    Create a sale and every side effect, in one transaction.

    Either the whole sale is committed (items, stock decrements, stock
    movements, customer balance) or nothing is. The old version tried to
    roll back by hand on failure; that block is gone.
    """

    allowed_roles = ["owner", "cashier"]

    def _error(self, request, message):
        return render(request, "sales/_receipt.html", {"error": message})

    def post(self, request, *args, **kwargs):
        org = self.get_organization()

        # ---- Payment method must be one we recognise ----
        payment_method = request.POST.get("payment_method", "cash")
        if payment_method not in VALID_PAYMENT_METHODS:
            return self._error(request, "Choose a valid payment method.")

        # ---- Customer must belong to THIS business ----
        customer = None
        customer_id = (request.POST.get("customer") or "").strip()
        if customer_id:
            if not customer_id.isdigit():
                return self._error(request, "Customer not found.")
            customer = Customer.objects.filter(
                pk=customer_id, organization=org, is_active=True
            ).first()
            if customer is None:
                return self._error(request, "Customer not found.")

        # A credit sale with no customer would silently lose the debt.
        if payment_method == "credit" and customer is None:
            return self._error(
                request,
                "Choose a customer for a credit sale, so the debt is recorded.",
            )

        wanted = _parse_lines(request.POST)
        if not wanted:
            return self._error(
                request, "Add at least one product before completing the sale."
            )

        try:
            with transaction.atomic():
                # Lock product rows so two cashiers can't sell the last
                # item at the same moment. select_for_update() is a no-op
                # on SQLite; production runs on PostgreSQL.
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

                sale = Sale.objects.create(
                    organization=org,
                    customer=customer,
                    payment_method=payment_method,
                    created_by=request.user,
                )

                total = Decimal("0")
                for pk, qty in wanted.items():
                    p = products[pk]
                    SaleItem.objects.create(
                        sale=sale,
                        product=p,
                        quantity=qty,
                        # Price comes from the database, never the browser.
                        unit_price=p.price,
                        # Snapshot cost so historical profit doesn't move
                        # when the product's cost is updated later.
                        unit_cost=p.cost_price,
                    )
                    Product.objects.filter(pk=pk).update(
                        stock_quantity=F("stock_quantity") - qty
                    )
                    StockMovement.objects.create(
                        organization=org,
                        product=p,
                        quantity=-qty,
                        movement_type="sale",
                        reference=f"Sale #{sale.pk}",
                    )
                    total += p.price * qty

                if total <= 0:
                    # Raising rolls the whole transaction back, including
                    # the Sale row already inserted above.
                    raise SaleError(
                        "Sale total is zero. Check that your products have prices set."
                    )

                sale.total = total
                sale.save(update_fields=["total"])

                if payment_method == "credit":
                    # Recalculate from source, don't add to the cached
                    # field. Lock the customer row too so this can't race
                    # a concurrent payment.
                    locked = Customer.objects.select_for_update().get(pk=customer.pk)
                    locked.update_balance()

        except SaleError as exc:
            return self._error(request, str(exc))

        if request.headers.get("HX-Request"):
            response = HttpResponse()
            response.headers["HX-Redirect"] = reverse("sale_list")
            return response
        return redirect(reverse("record_sale"))


# =============================================================================
# 5. Inventory list
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
# 6. Receive stock
# =============================================================================

class ReceiveStockView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin,
                       SubscriptionWriteRequiredMixin, FormView):
    """
    Receive stock from a supplier.

    Updates stock atomically and, if a unit cost is provided, updates the
    product's cost_price to a weighted average of old and new stock.
    """

    allowed_roles = ["owner", "stock_clerk"]
    template_name = "sales/receive_stock.html"
    form_class = ReceiveStockForm
    success_url = reverse_lazy("inventory_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        org = self.get_organization()
        quantity = form.cleaned_data["quantity"]
        supplier = form.cleaned_data.get("supplier")
        unit_cost = form.cleaned_data.get("unit_cost")

        # Lock the product row so a concurrent sale can't slip in between
        # the read of stock_quantity and the write.
        product = Product.objects.select_for_update().get(
            pk=form.cleaned_data["product"].pk,
            organization=org,
        )

        # Weighted-average cost update. Skip when no cost was entered —
        # the previous version silently left cost_price unchanged, which
        # is right, but it was never obvious.
        if unit_cost is not None:
            old_qty = max(product.stock_quantity, 0)
            old_cost = product.cost_price
            if old_cost is not None and old_qty > 0:
                product.cost_price = (
                    (old_qty * old_cost) + (quantity * unit_cost)
                ) / (old_qty + quantity)
            else:
                product.cost_price = unit_cost
            product.save(update_fields=["cost_price"])

        # F-expression update, no read-modify-write race.
        Product.objects.filter(pk=product.pk).update(
            stock_quantity=F("stock_quantity") + quantity
        )
        product.refresh_from_db(fields=["stock_quantity"])

        StockMovement.objects.create(
            organization=org,
            product=product,
            quantity=quantity,
            movement_type="purchase",
            reference=f"Received via {supplier.name if supplier else 'Manual'}",
            supplier=supplier,
        )

        messages.success(
            self.request,
            f"Received {quantity} {product.name}(s). "
            f"New stock: {product.stock_quantity}.",
        )
        return super().form_valid(form)


# =============================================================================
# 7. Stock valuation
# =============================================================================

class StockValuationView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    """
    Products with stock, their cost and retail values, and grand totals.

    Both totals are exposed. The old version counted stock only at
    selling price, which overstates what the stock is actually worth on
    the books — cost is the conservative figure an accountant would use.
    """

    allowed_roles = ["owner", "stock_clerk", "accountant"]
    template_name = "sales/stock_valuation.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        products = Product.objects.filter(organization=organization).order_by("name")

        total_retail = Decimal("0.00")
        total_cost = Decimal("0.00")

        for product in products:
            product.total_value = product.price * product.stock_quantity
            total_retail += product.total_value
            if product.cost_price is not None:
                product.cost_value = product.cost_price * product.stock_quantity
                total_cost += product.cost_value
            else:
                product.cost_value = None

        context["products"] = products
        context["total_value"] = total_retail
        context["total_cost_value"] = total_cost
        context["product_count"] = products.count()
        return context


# =============================================================================
# 8. Barcode scanning — sale form
# =============================================================================

class BarcodeScanView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    """
    HTMX: barcode → a new _item_row.html with the product preselected.

    Two bugs in the previous version are fixed here:
      * the POST handler read `barcode` and then ignored it
      * the "no product found" message printed the raw code, which is a
        reflected-XSS vector (a crafted link runs script in a logged-in
        owner's browser). escape() closes it.
    """

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
            organization=self.get_organization(), barcode=code
        ).first()
        if not product:
            return HttpResponse(
                f'<div class="alert alert-warning">'
                f'No product found for barcode {escape(code)}'
                f'</div>'
            )

        return render(request, "sales/_item_row.html", {
            "products": [product],
            "preselected": product.id,
        })

    def post(self, request):
        return self.get(request)


# =============================================================================
# 9. Barcode scanning — receive stock form
# =============================================================================

class BarcodeScanProductView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    """Same fixes as BarcodeScanView, returns _product_select.html instead."""

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
            organization=self.get_organization(), barcode=code
        ).first()
        if not product:
            return HttpResponse(
                f'<div class="alert alert-warning">'
                f'No product found for barcode {escape(code)}'
                f'</div>'
            )

        return render(request, "sales/_product_select.html", {
            "products": [product],
            "preselected": product.id,
        })

    def post(self, request):
        return self.get(request)


# =============================================================================
# 10. Product label (printable)
# =============================================================================

class ProductLabelView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, DetailView):
    """
    DetailView bypasses mixin get_queryset(); without the override below,
    /sales/product/<id>/label/ opens any business's product.
    """

    model = Product
    template_name = "sales/product_label.html"
    allowed_roles = ["owner", "stock_clerk"]

    def get_queryset(self):
        return Product.objects.filter(organization=self.get_organization())


# =============================================================================
# 11. Product CRUD
# =============================================================================

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
            self.request, f"Product '{form.instance.name}' added successfully."
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
            self.request, f"Product '{form.instance.name}' updated successfully."
        )
        return super().form_valid(form)