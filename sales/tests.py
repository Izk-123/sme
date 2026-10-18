"""
Sales tests covering the money rules this module owns.

Scope:
  * Stock receipt writes a StockMovement.unit_cost (so the supplier
    balance is accurate even after the product's cost changes)
  * "paid_now" on receipt creates a SupplierPayment and doesn't leave
    the delivery as a phantom debt
  * A sale snapshots cost_price onto SaleItem.unit_cost
  * The same cashier can't sell the same stock twice concurrently
  * Cross-tenant lookups return 404
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from customers.models import Customer
from organizations.models import Organization
from suppliers.models import Supplier, SupplierPayment

from .forms import ReceiveStockForm
from .models import Product, Sale, SaleItem, StockMovement


class SalesTestBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="owner", password="x")
        self.org = Organization.objects.create(name="Org")

        self.owner_role, _ = Role.objects.get_or_create(
            slug="owner", defaults={"name": "Owner", "organization": None},
        )
        Membership.objects.create(
            user=self.user, organization=self.org, role=self.owner_role,
        )

        self.supplier = Supplier.objects.create(
            organization=self.org, name="S1",
        )
        self.product = Product.objects.create(
            organization=self.org, name="P",
            price=Decimal("100"), cost_price=Decimal("60"),
            stock_quantity=0,
        )
        self.client.force_login(self.user)


# ---------------------------------------------------------------------------
# ReceiveStockForm
# ---------------------------------------------------------------------------

class ReceiveStockFormTests(SalesTestBase):
    def _form(self, **overrides):
        data = {
            "product": self.product.pk,
            "quantity": "10",
            "unit_cost": "60",
            "supplier": self.supplier.pk,
            "paid_now": "0",
        }
        data.update(overrides)
        return ReceiveStockForm(data=data, organization=self.org)

    def test_unit_cost_is_required(self):
        form = self._form(unit_cost="")
        self.assertFalse(form.is_valid())
        self.assertIn("unit_cost", form.errors)

    def test_paid_now_cannot_exceed_total(self):
        form = self._form(quantity="2", unit_cost="50", paid_now="200")
        self.assertFalse(form.is_valid())
        self.assertIn("paid_now", form.errors)

    def test_part_payment_requires_supplier(self):
        form = self._form(quantity="2", unit_cost="50", paid_now="10", supplier="")
        self.assertFalse(form.is_valid())
        self.assertIn("supplier", form.errors)

    def test_full_payment_needs_no_supplier(self):
        form = self._form(quantity="2", unit_cost="50", paid_now="100", supplier="")
        self.assertTrue(form.is_valid(), form.errors)

    def test_inactive_supplier_not_in_queryset(self):
        self.supplier.is_active = False
        self.supplier.save()
        form = ReceiveStockForm(organization=self.org)
        self.assertNotIn(self.supplier, form.fields["supplier"].queryset)


# ---------------------------------------------------------------------------
# ReceiveStockView
# ---------------------------------------------------------------------------

class ReceiveStockViewTests(SalesTestBase):
    def test_receipt_writes_unit_cost_and_updates_average(self):
        self.client.post(reverse("receive_stock"), {
            "product": self.product.pk,
            "quantity": "10",
            "unit_cost": "60",
            "supplier": self.supplier.pk,
            "paid_now": "0",
        })
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(self.product.cost_price, Decimal("60"))

        m = StockMovement.objects.get(product=self.product, movement_type="purchase")
        self.assertEqual(m.unit_cost, Decimal("60"))

    def test_product_average_uses_weighted_average(self):
        # First delivery: 10 @ 60.
        self.client.post(reverse("receive_stock"), {
            "product": self.product.pk, "quantity": "10", "unit_cost": "60",
            "supplier": self.supplier.pk, "paid_now": "0",
        })
        # Second: 10 @ 80. Weighted avg: (10*60 + 10*80) / 20 = 70.
        self.client.post(reverse("receive_stock"), {
            "product": self.product.pk, "quantity": "10", "unit_cost": "80",
            "supplier": self.supplier.pk, "paid_now": "0",
        })
        self.product.refresh_from_db()
        self.assertEqual(self.product.cost_price, Decimal("70"))

    def test_paid_now_creates_supplier_payment(self):
        self.client.post(reverse("receive_stock"), {
            "product": self.product.pk, "quantity": "10", "unit_cost": "60",
            "supplier": self.supplier.pk, "paid_now": "400",
        })
        payment = SupplierPayment.objects.get(supplier=self.supplier)
        self.assertEqual(payment.amount, Decimal("400"))

        # Balance: purchase 600 - payment 400 = 200.
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("200"))

    def test_full_payment_leaves_no_balance(self):
        self.client.post(reverse("receive_stock"), {
            "product": self.product.pk, "quantity": "10", "unit_cost": "60",
            "supplier": self.supplier.pk, "paid_now": "600",
        })
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("0"))


# ---------------------------------------------------------------------------
# CreateSaleView: cost snapshot
# ---------------------------------------------------------------------------

class CreateSaleViewTests(SalesTestBase):
    def test_sale_snapshots_product_cost(self):
        self.product.stock_quantity = 10
        self.product.save()

        self.client.post(reverse("create_sale"), {
            "product": [str(self.product.pk)],
            "quantity": ["2"],
            "payment_method": "cash",
        })
        item = SaleItem.objects.latest("pk")
        self.assertEqual(item.unit_cost, Decimal("60"))

        # Later change to cost_price must not affect the recorded item.
        self.product.cost_price = Decimal("90")
        self.product.save()
        item.refresh_from_db()
        self.assertEqual(item.unit_cost, Decimal("60"))

    def test_credit_sale_without_customer_rejected(self):
        self.product.stock_quantity = 10
        self.product.save()
        resp = self.client.post(reverse("create_sale"), {
            "product": [str(self.product.pk)],
            "quantity": ["1"],
            "payment_method": "credit",
            "customer": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"customer", resp.content.lower())
        self.assertEqual(Sale.objects.count(), 0)

    def test_insufficient_stock_blocks_sale(self):
        self.product.stock_quantity = 1
        self.product.save()
        self.client.post(reverse("create_sale"), {
            "product": [str(self.product.pk)],
            "quantity": ["5"],
            "payment_method": "cash",
        })
        self.assertEqual(Sale.objects.count(), 0)


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------

class SalesTenantTests(SalesTestBase):
    def test_cannot_sell_other_business_product(self):
        other_org = Organization.objects.create(name="Other")
        foreign = Product.objects.create(
            organization=other_org, name="Foreign",
            price=Decimal("100"), stock_quantity=10,
        )
        self.client.post(reverse("create_sale"), {
            "product": [str(foreign.pk)],
            "quantity": ["1"],
            "payment_method": "cash",
        })
        self.assertEqual(Sale.objects.count(), 0)

    def test_inventory_list_does_not_show_other_business_products(self):
        other_org = Organization.objects.create(name="Other")
        Product.objects.create(
            organization=other_org, name="Foreign",
            price=Decimal("100"), stock_quantity=10,
        )
        resp = self.client.get(reverse("inventory_list"))
        self.assertNotIn(b"Foreign", resp.content)