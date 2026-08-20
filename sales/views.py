# sales/views.py
"""
Sales and Inventory views for the SME Business OS.

This module contains all views related to sales transactions,
inventory management, stock receiving, and barcode scanning.
All views enforce role‑based access and organization scoping.
"""

from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    TemplateView,
    FormView,
    ListView,
    DetailView,
    UpdateView,
)

# Custom mixins for role and organization checks
from core.permissions import RoleRequiredMixin, OrganizationMixin
from customers.models import Customer
from .forms import ProductForm, ReceiveStockForm
from .models import Product, Sale, SaleItem, StockMovement


# =============================================================================
# 1. Sale List View
# =============================================================================

class SaleListView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, ListView):
    """
    Displays a paginated list of sales with optional filters.

    Filters:
    - customer (ID)
    - payment method
    - status (paid / due)
    - date (YYYY-MM-DD)

    Mobile displays cards, desktop uses a DataTable.
    """

    model = Sale
    template_name = "sales/sale_list.html"
    context_object_name = "sales"
    paginate_by = 20
    allowed_roles = ["owner", "cashier", "accountant"]

    def get_queryset(self):
        """Apply filters and return the filtered sales queryset."""
        qs = super().get_queryset().filter(
            organization=self.get_organization()
        ).select_related('customer').order_by('-created_at')

        # Filter by customer
        customer = self.request.GET.get('customer')
        if customer:
            qs = qs.filter(customer_id=customer)

        # Filter by payment method
        payment = self.request.GET.get('payment')
        if payment:
            qs = qs.filter(payment_method=payment)

        # Filter by status (paid = not credit, due = credit)
        status = self.request.GET.get('status')
        if status:
            if status == 'paid':
                qs = qs.exclude(payment_method='credit')
            elif status == 'due':
                qs = qs.filter(payment_method='credit')

        # Filter by date
        date = self.request.GET.get('date')
        if date:
            qs = qs.filter(created_at__date=date)

        return qs

    def get_context_data(self, **kwargs):
        """Add extra context for filters and KPI."""
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        today = timezone.now().date()

        # Customer dropdown options
        context['customers'] = Customer.objects.filter(organization=organization)

        # Today's sales total (used in the header)
        context['today_sales'] = float(Sale.objects.filter(
            organization=organization,
            created_at__date=today
        ).aggregate(total=Sum('total'))['total'] or 0)

        # Preserve filter selections
        context['selected_customer'] = self.request.GET.get('customer', '')
        context['selected_payment'] = self.request.GET.get('payment', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_date'] = self.request.GET.get('date', '')

        return context


# =============================================================================
# 2. Record Sale (Form Rendering)
# =============================================================================

class RecordSaleView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    """
    Renders the dynamic sale form with product and customer lists.
    The actual submission is handled by CreateSaleView via HTMX.
    """

    allowed_roles = ["owner", "cashier"]
    template_name = "sales/record_sale.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        context["products"] = Product.objects.filter(organization=organization)
        context["customers"] = Customer.objects.filter(organization=organization)
        return context


# =============================================================================
# 3. HTMX Helpers for Dynamic Sale Form
# =============================================================================

class AddItemRowView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    """
    HTMX endpoint: returns one new product/quantity row.
    Triggered by the '+ Add product' button.
    """

    allowed_roles = ["owner", "cashier"]
    template_name = "sales/_item_row.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["products"] = Product.objects.filter(organization=self.get_organization())
        return context


class RemoveItemRowView(LoginRequiredMixin, RoleRequiredMixin, View):
    """
    HTMX endpoint: deletes the calling row.
    The button uses hx-target="closest .item-row" and hx-swap="outerHTML".
    Returns an empty response because the row is removed client‑side.
    """

    allowed_roles = ["owner", "cashier"]

    def delete(self, request, *args, **kwargs):
        return HttpResponse("")

    def post(self, request, *args, **kwargs):
        return self.delete(request, *args, **kwargs)


class CalculateTotalsView(LoginRequiredMixin, RoleRequiredMixin, View):
    """
    HTMX endpoint: recalculates the grand total based on current form data.
    Triggered on any change (select, quantity, delete) inside the form.
    Returns the updated <div id="grand-total-wrapper">.
    """

    allowed_roles = ["owner", "cashier"]

    def post(self, request, *args, **kwargs):
        product_ids = request.POST.getlist("product")
        quantities = request.POST.getlist("quantity")

        total = Decimal("0")
        for product_id, qty in zip(product_ids, quantities):
            if not product_id or not qty:
                continue
            try:
                product = Product.objects.get(pk=product_id)
                total += product.price * int(qty)
            except (Product.DoesNotExist, ValueError):
                continue

        return render(request, "sales/_grand_total.html", {"total": total})


# =============================================================================
# 4. Create Sale (Actual Transaction)
# =============================================================================

class CreateSaleView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    """
    Processes the sale submission (HTMX POST).
    Validates stock availability, creates the sale, updates inventory,
    and returns a redirect (HX-Redirect) or an error message via _receipt.html.
    """

    allowed_roles = ["owner", "cashier"]

    def post(self, request, *args, **kwargs):
        organization = self.get_organization()
        customer_id = request.POST.get("customer")
        payment_method = request.POST.get("payment_method", "cash")

        product_ids = request.POST.getlist("product")
        quantities = request.POST.getlist("quantity")

        # ---------- Stock validation ----------
        errors = []
        for product_id, qty in zip(product_ids, quantities):
            if not product_id or not qty:
                continue
            try:
                product = Product.objects.get(pk=product_id)
                if product.stock_quantity < int(qty):
                    errors.append(
                        f"Not enough stock for {product.name} "
                        f"(available: {product.stock_quantity})"
                    )
            except Product.DoesNotExist:
                errors.append(f"Product #{product_id} not found")

        if errors:
            # Return error to _receipt.html (stays on page)
            return render(request, "sales/_receipt.html", {
                "error": " & ".join(errors)
            })

        # ---------- Create sale ----------
        sale = Sale.objects.create(
            organization=organization,
            customer_id=customer_id or None,
            payment_method=payment_method,
        )

        for product_id, qty in zip(product_ids, quantities):
            if not product_id or not qty:
                continue
            product = get_object_or_404(Product, pk=product_id)
            quantity = int(qty)

            SaleItem.objects.create(
                sale=sale,
                product=product,
                quantity=quantity,
                unit_price=product.price,
            )

            # Reduce stock
            product.stock_quantity -= quantity
            product.save(update_fields=["stock_quantity"])

            # Record stock movement (negative = out)
            StockMovement.objects.create(
                organization=organization,
                product=product,
                quantity=-quantity,
                movement_type="sale",
                reference=f"Sale #{sale.pk}"
            )

        # Recalculate sale total
        sale.recalculate_total()

        # Update customer's outstanding balance for credit sales
        if payment_method == "credit" and sale.customer:
            customer = sale.customer
            customer.outstanding_balance += sale.total
            customer.save(update_fields=["outstanding_balance"])

        # If HTMX request, return a redirect header to go to sales list
        if request.headers.get("HX-Request"):
            response = HttpResponse()
            response.headers['HX-Redirect'] = reverse('sale_list')
            return response

        # Fallback for non‑HTMX (should not happen)
        return redirect(reverse("record_sale"))


# =============================================================================
# 5. Inventory List
# =============================================================================

class InventoryListView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, ListView):
    """
    Displays a list of all products with stock levels and alerts.
    Supports client‑side search via the template.
    """

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
# 6. Receive Stock
# =============================================================================

class ReceiveStockView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, FormView):
    """
    Handles receiving new stock from suppliers.
    Increases product stock, creates a purchase stock movement,
    and links to the supplier (if provided).
    """

    allowed_roles = ["owner", "stock_clerk"]
    template_name = "sales/receive_stock.html"
    form_class = ReceiveStockForm
    success_url = reverse_lazy("inventory_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.get_organization()
        return kwargs

    def form_valid(self, form):
        product = form.cleaned_data["product"]
        quantity = form.cleaned_data["quantity"]
        supplier = form.cleaned_data.get("supplier")
        organization = self.get_organization()

        # Increase stock
        product.stock_quantity += quantity
        product.save(update_fields=["stock_quantity"])

        # Record stock movement (positive = in)
        StockMovement.objects.create(
            organization=organization,
            product=product,
            quantity=quantity,
            movement_type="purchase",
            reference=f"Received via {supplier.name if supplier else 'Manual'}",
            supplier=supplier
        )

        messages.success(
            self.request,
            f"Received {quantity} {product.name}(s) from "
            f"{supplier.name if supplier else 'Manual entry'}. "
            f"New stock: {product.stock_quantity}."
        )
        return super().form_valid(form)


# =============================================================================
# 7. Stock Valuation
# =============================================================================

class StockValuationView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    """
    Displays a table of all products with their current stock,
    unit price, total value (price × stock), and a grand total.
    """

    allowed_roles = ["owner", "stock_clerk", "accountant"]
    template_name = "sales/stock_valuation.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        products = Product.objects.filter(organization=organization).order_by("name")

        total_value = Decimal("0.00")
        for product in products:
            product.total_value = product.price * product.stock_quantity
            total_value += product.total_value

        context["products"] = products
        context["total_value"] = total_value
        context["product_count"] = products.count()
        return context


# =============================================================================
# 8. Barcode Scanning (for adding items to a sale)
# =============================================================================

class BarcodeScanView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    """
    HTMX endpoint: accepts a barcode (GET or POST), finds the product,
    and returns a new _item_row.html with the product preselected.
    Used by the USB scanner input and the camera scanner.
    """

    allowed_roles = ["owner", "cashier"]

    def get(self, request):
        code = request.GET.get("code", "")
        if not code:
            return HttpResponse("")

        product = Product.objects.filter(
            organization=self.get_organization(),
            barcode=code
        ).first()
        if not product:
            return HttpResponse(
                f'<div class="alert alert-warning">No product found for barcode {code}</div>'
            )

        return render(request, "sales/_item_row.html", {
            "products": [product],
            "preselected": product.id,
        })

    def post(self, request):
        code = request.POST.get("barcode")
        return self.get(request)


# =============================================================================
# 9. Barcode Scanning (for pre‑selecting product in Receive Stock)
# =============================================================================

class BarcodeScanProductView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    """
    HTMX endpoint for the Receive Stock form.
    Accepts a barcode and returns a _product_select.html partial
    with the matching product preselected.
    """

    allowed_roles = ["owner", "stock_clerk"]

    def get(self, request):
        code = request.GET.get("code", "")
        if not code:
            return render(request, "sales/_product_select.html", {"products": []})

        product = Product.objects.filter(
            organization=self.get_organization(),
            barcode=code
        ).first()
        if not product:
            return HttpResponse(
                f'<div class="alert alert-warning">No product found for barcode {code}</div>'
            )

        return render(request, "sales/_product_select.html", {
            "products": [product],
            "preselected": product.id,
        })


# =============================================================================
# 10. Product Label (printable barcode label)
# =============================================================================

class ProductLabelView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, DetailView):
    """
    Renders a printable label containing the product name,
    barcode, and price. The template triggers window.print()
    on load.
    """

    model = Product
    template_name = "sales/product_label.html"
    allowed_roles = ["owner", "stock_clerk"]
    
# =============================================================================
# 11. Product CRUD (Add / Edit)
# =============================================================================

class ProductCreateView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, CreateView):
    """
    Frontend form to add a new product to the inventory.
    """
    model = Product
    form_class = ProductForm
    template_name = "sales/product_form.html"
    success_url = reverse_lazy("inventory_list")
    allowed_roles = ["owner", "stock_clerk"]

    def form_valid(self, form):
        # Automatically assign the current organization
        form.instance.organization = self.get_organization()
        messages.success(self.request, f"Product '{form.instance.name}' added successfully.")
        return super().form_valid(form)


class ProductUpdateView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, UpdateView):
    """
    Frontend form to edit an existing product.
    """
    model = Product
    form_class = ProductForm
    template_name = "sales/product_form.html"
    success_url = reverse_lazy("inventory_list")
    allowed_roles = ["owner", "stock_clerk"]

    def get_queryset(self):
        # Ensure the user can only edit products from their own organization
        return super().get_queryset().filter(organization=self.get_organization())

    def form_valid(self, form):
        messages.success(self.request, f"Product '{form.instance.name}' updated successfully.")
        return super().form_valid(form)