from django.test import TestCase

# Create your tests here.

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import Expense, ExpenseCategory
from organizations.models import Organization
from sales.models import Product, StockMovement

from .models import Supplier, SupplierPayment


class SupplierBalanceTests(TestCase):
    """Verify that Supplier.outstanding_balance tracks purchases + expenses - payments."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="t", password="x")
        self.org = Organization.objects.create(name="Org", owner=self.user)
        self.supplier = Supplier.objects.create(organization=self.org, name="S1")
        self.product = Product.objects.create(
            organization=self.org,
            name="P",
            price=Decimal("100"),
            cost_price=Decimal("60"),
            stock_quantity=0,
        )
        self.cat = ExpenseCategory.objects.create(
            organization=self.org, name="Delivery"
        )

    def test_balance_reflects_purchase_expense_payment(self):
        StockMovement.objects.create(
            organization=self.org,
            product=self.product,
            quantity=10,
            movement_type="purchase",
            supplier=self.supplier,
        )  # 10 x 60 = 600
        Expense.objects.create(
            organization=self.org,
            date="2026-01-01",
            category=self.cat,
            amount=Decimal("150"),
            supplier=self.supplier,
            created_by=self.user,
        )
        SupplierPayment.objects.create(
            organization=self.org,
            supplier=self.supplier,
            date="2026-01-02",
            amount=Decimal("200"),
            method="cash",
            created_by=self.user,
        )

        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("550.00"))

    def test_balance_self_heals_after_delete(self):
        m = StockMovement.objects.create(
            organization=self.org,
            product=self.product,
            quantity=5,
            movement_type="purchase",
            supplier=self.supplier,
        )
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("300.00"))
        m.delete()
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("0.00"))

