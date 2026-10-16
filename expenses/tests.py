from django.test import TestCase

# Create your tests here.

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from organizations.models import Organization
from suppliers.models import Supplier

from .models import Expense, ExpenseCategory


class ExpenseSupplierFKTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="t", password="x")
        self.org = Organization.objects.create(name="TestOrg", owner=self.user)
        self.supplier = Supplier.objects.create(
            organization=self.org, name="ABC Distributors"
        )
        self.category = ExpenseCategory.objects.create(
            organization=self.org, name="Packaging"
        )

    def test_expense_can_link_to_supplier(self):
        e = Expense.objects.create(
            organization=self.org,
            date="2026-01-01",
            category=self.category,
            amount=Decimal("500.00"),
            supplier=self.supplier,
            created_by=self.user,
        )
        self.assertEqual(e.supplier, self.supplier)
        self.assertIn(e, self.supplier.expenses.all())

    def test_expense_can_be_supplierless(self):
        e = Expense.objects.create(
            organization=self.org,
            date="2026-01-01",
            category=self.category,
            amount=Decimal("100.00"),
            supplier=None,
            created_by=self.user,
        )
        self.assertIsNone(e.supplier)

