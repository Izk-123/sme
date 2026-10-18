"""
Supplier tests.

Scope:
  * balance correctness (purchases, unpaid expenses, payments, opening
    balance, historical cost stability)
  * cross-tenant isolation at the form and view level
  * payment list pagination works past page 1
  * supplier form rejects duplicate names
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Role
from expenses.models import Expense, ExpenseCategory
from organizations.models import Organization
from sales.models import Product, StockMovement

from .forms import SupplierForm
from .models import Supplier, SupplierPayment


class SupplierTestBase(TestCase):
    """Shared fixture: user + org + owner membership + supplier + product."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="owner", password="x")
        self.org = Organization.objects.create(name="Org")

        # Ownership lives on Membership — Organization has no `owner` FK.
        self.owner_role, _ = Role.objects.get_or_create(
            slug="owner", defaults={"name": "Owner", "organization": None}
        )
        Membership.objects.create(
            user=self.user, organization=self.org, role=self.owner_role,
        )

        self.supplier = Supplier.objects.create(
            organization=self.org, name="S1",
        )
        self.product = Product.objects.create(
            organization=self.org,
            name="P",
            price=Decimal("100"),
            cost_price=Decimal("60"),
            stock_quantity=0,
        )
        self.cat = ExpenseCategory.objects.create(
            organization=self.org, name="Delivery",
        )


# ---------------------------------------------------------------------------
# Balance arithmetic
# ---------------------------------------------------------------------------

class SupplierBalanceTests(SupplierTestBase):
    def test_opening_balance_included(self):
        self.supplier.opening_balance = Decimal("500.00")
        self.supplier.save()
        self.supplier.update_balance()
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("500.00"))

    def test_balance_reflects_purchase_payment_and_unpaid_expense(self):
        StockMovement.objects.create(
            organization=self.org, product=self.product, quantity=10,
            unit_cost=Decimal("60"), movement_type="purchase",
            supplier=self.supplier,
        )  # 10 × 60 = 600
        Expense.objects.create(
            organization=self.org, date="2026-01-01", category=self.cat,
            amount=Decimal("150"), supplier=self.supplier,
            on_credit=True, created_by=self.user,
        )
        SupplierPayment.objects.create(
            organization=self.org, supplier=self.supplier,
            date="2026-01-02", amount=Decimal("200"), method="cash",
            created_by=self.user,
        )
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("550.00"))

    def test_cash_paid_expense_does_not_count(self):
        Expense.objects.create(
            organization=self.org, date="2026-01-01", category=self.cat,
            amount=Decimal("150"), supplier=self.supplier,
            on_credit=False, created_by=self.user,
        )
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("0.00"))

    def test_changing_product_cost_does_not_move_old_balance(self):
        StockMovement.objects.create(
            organization=self.org, product=self.product, quantity=10,
            unit_cost=Decimal("60"), movement_type="purchase",
            supplier=self.supplier,
        )
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("600.00"))

        # Product's cost goes up — the OLD delivery must stay at 60.
        self.product.cost_price = Decimal("90")
        self.product.save()

        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("600.00"))

    def test_balance_self_heals_after_delete(self):
        m = StockMovement.objects.create(
            organization=self.org, product=self.product, quantity=5,
            unit_cost=Decimal("60"), movement_type="purchase",
            supplier=self.supplier,
        )
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("300.00"))

        m.delete()
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("0.00"))

    def test_expense_moved_to_other_supplier_refreshes_both(self):
        other = Supplier.objects.create(organization=self.org, name="S2")
        expense = Expense.objects.create(
            organization=self.org, date="2026-01-01", category=self.cat,
            amount=Decimal("200"), supplier=self.supplier,
            on_credit=True, created_by=self.user,
        )
        self.supplier.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("200.00"))
        self.assertEqual(other.outstanding_balance, Decimal("0.00"))

        expense.supplier = other
        expense.save(update_fields=["supplier"])

        self.supplier.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("0.00"))
        self.assertEqual(other.outstanding_balance, Decimal("200.00"))

    def test_purchase_flipped_to_sale_refreshes_balance(self):
        m = StockMovement.objects.create(
            organization=self.org, product=self.product, quantity=5,
            unit_cost=Decimal("60"), movement_type="purchase",
            supplier=self.supplier,
        )
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("300.00"))

        m.movement_type = "sale"
        m.save(update_fields=["movement_type"])

        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("0.00"))


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------

class SupplierFormTests(SupplierTestBase):
    def test_duplicate_name_rejected_in_same_org(self):
        form = SupplierForm(
            data={"name": "S1", "opening_balance": "0"},
            organization=self.org,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_duplicate_name_allowed_in_other_org(self):
        other_org = Organization.objects.create(name="Other")
        form = SupplierForm(
            data={"name": "S1", "opening_balance": "0"},
            organization=other_org,
        )
        self.assertTrue(form.is_valid())

    def test_editing_keeps_own_name_valid(self):
        form = SupplierForm(
            data={"name": "S1", "opening_balance": "0"},
            instance=self.supplier, organization=self.org,
        )
        self.assertTrue(form.is_valid())


class SupplierPaymentFormTests(SupplierTestBase):
    def test_negative_payment_rejected(self):
        from .forms import SupplierPaymentForm
        form = SupplierPaymentForm(
            data={
                "supplier": self.supplier.pk, "date": "2026-01-01",
                "amount": "-50", "method": "cash",
            },
            organization=self.org,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_zero_payment_rejected(self):
        from .forms import SupplierPaymentForm
        form = SupplierPaymentForm(
            data={
                "supplier": self.supplier.pk, "date": "2026-01-01",
                "amount": "0", "method": "cash",
            },
            organization=self.org,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_payment_for_other_tenant_supplier_rejected(self):
        other_org = Organization.objects.create(name="Other")
        foreign = Supplier.objects.create(organization=other_org, name="Foreign")
        from .forms import SupplierPaymentForm
        form = SupplierPaymentForm(
            data={
                "supplier": foreign.pk, "date": "2026-01-01",
                "amount": "50", "method": "cash",
            },
            organization=self.org,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("supplier", form.errors)


# ---------------------------------------------------------------------------
# Views: tenant isolation and pagination
# ---------------------------------------------------------------------------

class SupplierTenantIsolationTests(SupplierTestBase):
    def test_detail_view_does_not_leak_across_tenants(self):
        other_org = Organization.objects.create(name="Other")
        foreign = Supplier.objects.create(organization=other_org, name="Foreign")

        self.client.force_login(self.user)
        resp = self.client.get(reverse("supplier_detail", kwargs={"pk": foreign.pk}))
        self.assertEqual(resp.status_code, 404)

    def test_payment_post_for_other_tenant_supplier_blocked(self):
        other_org = Organization.objects.create(name="Other")
        foreign = Supplier.objects.create(organization=other_org, name="Foreign")

        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("supplier_payment_add"),
            data={
                "supplier": foreign.pk, "date": "2026-01-01",
                "amount": "50", "method": "cash",
            },
        )
        # Form error re-renders with 200, not a 302 redirect.
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(SupplierPayment.objects.count(), 0)


class SupplierPaymentPaginationTests(SupplierTestBase):
    def test_page_2_reachable(self):
        for i in range(25):
            SupplierPayment.objects.create(
                organization=self.org, supplier=self.supplier,
                date="2026-01-01", amount=Decimal("10"), method="cash",
                created_by=self.user,
            )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("supplier_payment_list") + "?page=2")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["payments"]), 5)