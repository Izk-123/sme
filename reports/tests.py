"""
Finance rule tests.

These pin the accounting contract:
  * P&L uses cost of goods, not just revenue − expenses.
  * Snapshotted costs never move when a product's cost changes later.
  * Cash counts only money that actually moved (no credit sales,
    no unpaid expenses, includes customer repayments and supplier
    payments).
  * Multi-tenancy holds.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Customer, Payment as CustomerPayment
from expenses.models import Expense, ExpenseCategory
from organizations.models import Organization
from sales.models import Product, Sale, SaleItem
from suppliers.models import Supplier, SupplierPayment

from .finance import period_figures


class FinanceRulesTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="O")
        self.other = Organization.objects.create(name="Other")
        self.p = Product.objects.create(
            organization=self.org, name="P", price=Decimal("100"),
            cost_price=Decimal("60"), stock_quantity=100,
        )
        self.cat = ExpenseCategory.objects.create(
            organization=self.org, name="Delivery",
        )
        self.day = timezone.localdate()

    def _sale(self, qty, method="cash", cost=Decimal("60"), org=None):
        org = org or self.org
        s = Sale.objects.create(
            organization=org, payment_method=method,
            total=Decimal("100") * qty,
        )
        SaleItem.objects.create(
            sale=s, product=self.p, quantity=qty,
            unit_price=Decimal("100"), unit_cost=cost,
        )
        return s

    def test_profit_uses_cost_of_goods(self):
        self._sale(10)
        Expense.objects.create(
            organization=self.org, date=self.day,
            category=self.cat, amount=Decimal("150"),
        )
        f = period_figures(self.org, self.day, self.day)
        self.assertEqual(
            (f["revenue"], f["cogs"], f["gross_profit"], f["net_profit"]),
            (Decimal("1000"), Decimal("600"), Decimal("400"), Decimal("250")),
        )

    def test_snapshotted_cost_does_not_drift(self):
        self._sale(10)
        Expense.objects.create(
            organization=self.org, date=self.day,
            category=self.cat, amount=Decimal("150"),
        )
        # Change cost_price AFTER the sale. The sale's own unit_cost
        # must keep the profit at 250.
        self.p.cost_price = Decimal("90")
        self.p.save()
        self.assertEqual(
            period_figures(self.org, self.day, self.day)["net_profit"],
            Decimal("250"),
        )

    def test_cash_report_counts_only_money_that_moved(self):
        self._sale(10)                          # 1000 cash
        self._sale(5, method="credit")          # 500 not yet paid
        customer = Customer.objects.create(organization=self.org, name="C")
        CustomerPayment.objects.create(
            organization=self.org, customer=customer, amount=Decimal("200"),
        )
        Expense.objects.create(
            organization=self.org, date=self.day, category=self.cat,
            amount=Decimal("300"), on_credit=True,
        )
        Expense.objects.create(
            organization=self.org, date=self.day, category=self.cat,
            amount=Decimal("100"), on_credit=False,
        )
        supplier = Supplier.objects.create(organization=self.org, name="S")
        SupplierPayment.objects.create(
            organization=self.org, supplier=supplier,
            date=self.day, amount=Decimal("50"),
        )
        f = period_figures(self.org, self.day, self.day)
        self.assertEqual(f["cash_in"], Decimal("1200"))   # 1000 + 200
        self.assertEqual(f["cash_out"], Decimal("150"))   # 100 + 50

    def test_unknown_cost_is_flagged(self):
        self.p.cost_price = None
        self.p.save()
        self._sale(1, cost=None)
        f = period_figures(self.org, self.day, self.day)
        self.assertEqual(f["unknown_cost_lines"], 1)

    def test_other_business_is_excluded(self):
        self._sale(10, org=self.other)
        f = period_figures(self.org, self.day, self.day)
        self.assertEqual(f["revenue"], Decimal("0"))