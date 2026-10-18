"""
One definition of every money figure in the app.

The two rules:
  * P&L (accrual): revenue counts when a sale happens. Expenses count
    when incurred. COGS is the snapshotted SaleItem.unit_cost.
  * Cash (cash basis): counts only money that moved. Sale.amount_paid
    (cash at sale) + CustomerPayment.amount (repayments) on the way in;
    paid expenses + SupplierPayment.amount on the way out.

Third rule: everything is filtered by organization and by __date /
__range so timezone handling is consistent across all reports.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import (
    Count, DecimalField, ExpressionWrapper, F, Q, Sum,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from customers.models import Customer, Payment as CustomerPayment
from expenses.models import Expense
from sales.models import Sale, SaleItem
from suppliers.models import Supplier, SupplierPayment

ZERO = Decimal("0.00")
MONEY = DecimalField(max_digits=14, decimal_places=2)

# COGS per unit: snapshotted cost, else the current product cost.
LINE_COST = Coalesce(
    F("unit_cost"),
    F("product__cost_price"),
    output_field=DecimalField(max_digits=12, decimal_places=2),
)

# Unpaid per sale: total - amount_paid.
UNPAID_PER_SALE = ExpressionWrapper(
    F("total") - F("amount_paid"), output_field=MONEY,
)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def today():
    return timezone.localdate()


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def previous_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def pct_change(current, previous):
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def _sum(qs, field):
    return qs.aggregate(t=Sum(field))["t"] or ZERO


# ---------------------------------------------------------------------------
# The one money report
# ---------------------------------------------------------------------------

def period_figures(org, start, end):
    sales = Sale.objects.filter(
        organization=org, created_at__date__range=(start, end),
    )
    items = SaleItem.objects.filter(
        sale__organization=org, sale__created_at__date__range=(start, end),
    )
    expenses = Expense.objects.filter(organization=org, date__range=(start, end))

    # Revenue is everything invoiced, credit or cash.
    revenue = _sum(sales, "total")

    # "Credit sales" = the portion NOT collected at the time of sale.
    # Summing total - amount_paid across every sale gives that figure
    # exactly: a fully-paid sale contributes 0; a fully-credit sale
    # contributes its total; a partial sale contributes its unpaid
    # part.
    credit_sales = (
        sales.aggregate(t=Sum(UNPAID_PER_SALE))["t"] or ZERO
    )
    cash_sales = revenue - credit_sales

    cogs = items.aggregate(
        t=Sum(ExpressionWrapper(F("quantity") * LINE_COST, output_field=MONEY))
    )["t"] or ZERO

    unknown_cost_lines = items.filter(
        unit_cost__isnull=True, product__cost_price__isnull=True,
    ).count()

    total_expenses = _sum(expenses, "amount")
    unpaid_expenses = _sum(expenses.filter(on_credit=True), "amount")

    customer_payments = _sum(
        CustomerPayment.objects.filter(
            organization=org, created_at__date__range=(start, end),
        ), "amount",
    )
    supplier_payments = _sum(
        SupplierPayment.objects.filter(
            organization=org, date__range=(start, end),
        ), "amount",
    )

    gross_profit = revenue - cogs
    net_profit = gross_profit - total_expenses
    cash_in = cash_sales + customer_payments
    cash_out = (total_expenses - unpaid_expenses) + supplier_payments

    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_margin": round(gross_profit / revenue * 100, 1) if revenue else None,
        "expenses": total_expenses,
        "net_profit": net_profit,
        "unknown_cost_lines": unknown_cost_lines,
        "credit_sales": credit_sales,
        "cash_sales": cash_sales,
        "customer_payments": customer_payments,
        "supplier_payments": supplier_payments,
        "paid_expenses": total_expenses - unpaid_expenses,
        "unpaid_expenses": unpaid_expenses,
        "cash_in": cash_in,
        "cash_out": cash_out,
        "net_cash": cash_in - cash_out,
    }


# ---------------------------------------------------------------------------
# Per-product / per-category breakdowns
# ---------------------------------------------------------------------------

def product_profit(org, start, end, limit=10):
    return (
        SaleItem.objects.filter(
            sale__organization=org, sale__created_at__date__range=(start, end),
        )
        .values("product__name")
        .annotate(
            qty=Sum("quantity"),
            revenue=Sum(ExpressionWrapper(
                F("quantity") * F("unit_price"), output_field=MONEY)),
            cost=Coalesce(
                Sum(ExpressionWrapper(F("quantity") * LINE_COST, output_field=MONEY)),
                ZERO, output_field=MONEY,
            ),
            unknown=Count("id", filter=Q(
                unit_cost__isnull=True, product__cost_price__isnull=True)),
        )
        .annotate(profit=ExpressionWrapper(
            F("revenue") - F("cost"), output_field=MONEY))
        .order_by("-profit")[:limit]
    )


def expenses_by_category(org, start, end):
    return (
        Expense.objects.filter(organization=org, date__range=(start, end))
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )


# ---------------------------------------------------------------------------
# Debts
# ---------------------------------------------------------------------------

def receivables(org):
    qs = (
        Customer.objects.filter(organization=org, outstanding_balance__gt=0)
        .order_by("-outstanding_balance")
    )
    return qs, _sum(qs, "outstanding_balance")


def payables(org):
    qs = (
        Supplier.objects.filter(organization=org, outstanding_balance__gt=0)
        .order_by("-outstanding_balance")
    )
    return qs, _sum(qs, "outstanding_balance")


# ---------------------------------------------------------------------------
# Debt ageing
# ---------------------------------------------------------------------------

def _age_bucket(days_overdue):
    """Return one of 'current', '1_30', '31_60', '61_plus'."""
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "1_30"
    if days_overdue <= 60:
        return "31_60"
    return "61_plus"


def debt_ageing(org):
    """
    Per-customer ageing of what they owe.

    Walks each customer's sales, computes what's still open on each one
    (total - amount_paid - sum of allocations), and buckets by how long
    it's been past its due date. Falls back to created_at + 30 days as
    an implicit due date when Sale.due_date is empty.

    A customer's `prior_or_opening` bucket reconciles the ageing
    against `customer.calculate_balance()` — it holds the opening
    balance (which has no sale to attach to) plus any unallocated
    payments the customer has made.
    """
    today_ = today()
    rows = []

    customers = (
        Customer.objects.filter(organization=org)
        .prefetch_related("sales", "payments")
    )

    for customer in customers:
        total_owed = customer.calculate_balance()
        if total_owed <= 0:
            continue

        buckets = {
            "current": ZERO, "1_30": ZERO, "31_60": ZERO, "61_plus": ZERO,
        }

        for sale in customer.sales.filter(organization=org):
            already_allocated = sum(
                (a.amount for a in sale.payment_allocations.all()), ZERO,
            )
            open_amount = sale.total - sale.amount_paid - already_allocated
            if open_amount <= 0:
                continue

            ref_due = sale.due_date or (sale.created_at.date() + timedelta(days=30))
            days_overdue = (today_ - ref_due).days
            bucket = _age_bucket(days_overdue)
            buckets[bucket] += open_amount

        aged_total = sum(buckets.values(), ZERO)
        # Reconcile with the authoritative balance.
        prior_or_opening = total_owed - aged_total

        rows.append({
            "customer": customer,
            "current": buckets["current"],
            "1_30": buckets["1_30"],
            "31_60": buckets["31_60"],
            "61_plus": buckets["61_plus"],
            "prior_or_opening": prior_or_opening,
            "total_owed": total_owed,
        })

    rows.sort(key=lambda r: r["total_owed"], reverse=True)
    return rows