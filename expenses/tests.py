"""
Expense tests.

Scope:
  * the two money rules introduced with on_credit / payment_method
  * the stock double-count guard
  * the delete success message actually fires (the old override didn't)
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Role
from organizations.models import Organization
from suppliers.models import Supplier

from .forms import ExpenseForm
from .models import Expense, ExpenseCategory


class ExpenseTestBase(TestCase):
    """Shared fixture: user + org + owner membership + supplier."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="owner", password="x")
        # Organization has no `owner` field — ownership lives on
        # Membership. The old fixture `Organization(owner=...)` failed
        # in setUp with a TypeError on every test.
        self.org = Organization.objects.create(name="TestOrg")
        self.owner_role, _ = Role.objects.get_or_create(
            slug="owner", defaults={"name": "Owner", "organization": None},
        )
        Membership.objects.create(
            user=self.user, organization=self.org, role=self.owner_role,
        )
        self.supplier = Supplier.objects.create(
            organization=self.org, name="ABC Distributors",
        )
        self.category = ExpenseCategory.objects.create(
            organization=self.org, name="Packaging",
        )


# ---------------------------------------------------------------------------
# Model-level: FK to supplier still works
# ---------------------------------------------------------------------------

class ExpenseSupplierFKTests(ExpenseTestBase):
    def test_expense_can_link_to_supplier(self):
        e = Expense.objects.create(
            organization=self.org, date="2026-01-01", category=self.category,
            amount=Decimal("500.00"), supplier=self.supplier,
            created_by=self.user,
        )
        self.assertEqual(e.supplier, self.supplier)
        self.assertIn(e, self.supplier.expenses.all())

    def test_expense_can_be_supplierless(self):
        e = Expense.objects.create(
            organization=self.org, date="2026-01-01", category=self.category,
            amount=Decimal("100.00"), supplier=None, created_by=self.user,
        )
        self.assertIsNone(e.supplier)


# ---------------------------------------------------------------------------
# Form: on_credit / payment_method rules
# ---------------------------------------------------------------------------

class ExpenseFormMoneyRulesTests(ExpenseTestBase):
    def test_on_credit_requires_a_supplier(self):
        form = ExpenseForm(
            data={
                "date": "2026-01-01", "category_name": "Delivery",
                "amount": "200", "supplier": "", "on_credit": "on",
                "payment_method": "cash",  # will be ignored/cleared
            },
            organization=self.org,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("supplier", form.errors)

    def test_on_credit_clears_payment_method(self):
        form = ExpenseForm(
            data={
                "date": "2026-01-01", "category_name": "Delivery",
                "amount": "200", "supplier": self.supplier.pk,
                "on_credit": "on", "payment_method": "cash",
            },
            organization=self.org,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["payment_method"], "")

    def test_cash_paid_expense_keeps_payment_method(self):
        form = ExpenseForm(
            data={
                "date": "2026-01-01", "category_name": "Delivery",
                "amount": "200", "supplier": self.supplier.pk,
                "on_credit": "", "payment_method": "cash",
            },
            organization=self.org,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["payment_method"], "cash")


# ---------------------------------------------------------------------------
# Form: stock double-count guard
# ---------------------------------------------------------------------------

class ExpenseStockCategoryBlockTests(ExpenseTestBase):
    def _form(self, category_name):
        return ExpenseForm(
            data={
                "date": "2026-01-01", "category_name": category_name,
                "amount": "500", "supplier": "", "on_credit": "",
                "payment_method": "",
            },
            organization=self.org,
        )

    def test_stock_categories_are_blocked(self):
        for name in ("Stock", "purchases", "GOODS", "Inventory"):
            with self.subTest(name=name):
                form = self._form(name)
                self.assertFalse(form.is_valid())
                self.assertIn("category_name", form.errors)

    def test_ordinary_categories_pass(self):
        for name in ("Delivery", "Rent", "Packaging"):
            with self.subTest(name=name):
                form = self._form(name)
                self.assertTrue(form.is_valid(), form.errors)


# ---------------------------------------------------------------------------
# Cross-tenant supplier dropdown
# ---------------------------------------------------------------------------

class ExpenseFormTenantTests(ExpenseTestBase):
    def test_foreign_supplier_not_in_dropdown(self):
        other_org = Organization.objects.create(name="Other")
        foreign = Supplier.objects.create(organization=other_org, name="Foreign")
        form = ExpenseForm(organization=self.org)
        suppliers = set(form.fields["supplier"].queryset)
        self.assertIn(self.supplier, suppliers)
        self.assertNotIn(foreign, suppliers)


# ---------------------------------------------------------------------------
# Delete view: success message now fires
# ---------------------------------------------------------------------------

class ExpenseDeleteViewTests(ExpenseTestBase):
    def test_delete_shows_success_message(self):
        e = Expense.objects.create(
            organization=self.org, date="2026-01-01",
            category=self.category, amount=Decimal("100"),
            created_by=self.user,
        )
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("expense_delete", kwargs={"pk": e.pk}),
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Expense.objects.filter(pk=e.pk).exists())

        all_messages = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertIn("Expense deleted.", all_messages)

    def test_delete_other_tenant_returns_404(self):
        other_org = Organization.objects.create(name="Other")
        foreign = Expense.objects.create(
            organization=other_org, date="2026-01-01",
            category=None, amount=Decimal("100"), created_by=self.user,
        )
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("expense_delete", kwargs={"pk": foreign.pk}),
        )
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Expense.objects.filter(pk=foreign.pk).exists())