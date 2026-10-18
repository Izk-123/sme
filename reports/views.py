"""
Views for the Reports app.

Every money number comes from finance.period_figures(). If two reports
disagree, only finance.py is wrong.
"""
import calendar
from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import F, Sum
from django.db.models.functions import ExtractMonth
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.views import View
from django.views.generic import TemplateView

from core.permissions import OrganizationMixin, RoleRequiredMixin
from expenses.models import Expense
from sales.models import Sale, SaleItem

from . import finance, services
from .finance import (
    month_bounds, payables, period_figures, pct_change,
    previous_month, product_profit, receivables, today,
)
from .forms import MonthYearForm, SalesReportForm, YearForm


class ReportMixin(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin):
    allowed_roles = ["owner", "accountant"]


def _month_year(request):
    now = today()
    form = MonthYearForm(request.GET or {"month": now.month, "year": now.year})
    if form.is_valid():
        return form, int(form.cleaned_data["month"]), int(form.cleaned_data["year"])
    return form, now.month, now.year


def _int_or(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ReportIndexView(ReportMixin, TemplateView):
    template_name = "reports/index.html"


class BusinessPerformanceView(ReportMixin, View):
    template_name = "reports/business_performance.html"

    def get(self, request):
        org = self.get_organization()
        now = today()
        start = now.replace(day=1)
        py, pm = previous_month(now.year, now.month)
        prev_start, prev_last = month_bounds(py, pm)
        prev_end = min(prev_start + timedelta(days=now.day - 1), prev_last)

        cur = period_figures(org, start, now)
        prev = period_figures(org, prev_start, prev_end)

        def legacy(f):
            return {
                **f,
                "total_sales": f["revenue"],
                "total_expenses": f["expenses"],
                "cash_received": f["cash_in"],
                "customer_credit": f["credit_sales"],
            }

        return render(request, self.template_name, {
            "current": legacy(cur),
            "previous": legacy(prev),
            "change": {
                "sales": pct_change(cur["revenue"], prev["revenue"]),
                "expenses": pct_change(cur["expenses"], prev["expenses"]),
                "profit": pct_change(cur["net_profit"], prev["net_profit"]),
            },
        })


class ProfitLossView(ReportMixin, TemplateView):
    template_name = "reports/profit_loss.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.get_organization()
        form, month, year = _month_year(self.request)
        start, end = month_bounds(year, month)
        f = period_figures(org, start, end)
        context.update(f)
        context.update(
            form=form, month=month, year=year,
            expense_categories=finance.expenses_by_category(org, start, end),
            product_profit=product_profit(org, start, end),
        )
        return context


class CashReportView(ReportMixin, TemplateView):
    template_name = "reports/cash_report.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.get_organization()
        form, month, year = _month_year(self.request)
        start, end = month_bounds(year, month)
        context.update(period_figures(org, start, end))
        context.update(form=form, month=month, year=year)
        context["customers_owing"], context["total_owed_to_you"] = receivables(org)
        context["suppliers_owed"], context["total_you_owe"] = payables(org)
        return context


class SupplierPayablesView(ReportMixin, TemplateView):
    template_name = "reports/supplier_payables.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["suppliers"], context["total_you_owe"] = payables(self.get_organization())
        return context


class InventoryStockView(ReportMixin, TemplateView):
    allowed_roles = ["owner", "stock_clerk", "accountant"]
    template_name = "reports/inventory_stock.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.get_organization()
        products = list(services.get_current_stock(org))
        context["products"] = products
        context["low_stock"] = services.get_low_stock(org)
        context["total_retail_value"] = sum(
            (p.retail_value for p in products), finance.ZERO,
        )
        context["total_cost_value"] = sum(
            (p.cost_value for p in products if p.cost_value is not None),
            finance.ZERO,
        )
        context["missing_cost_count"] = sum(
            1 for p in products if p.cost_price is None
        )
        return context


class CustomerDebtView(ReportMixin, TemplateView):
    template_name = "reports/customer_debt.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customers, total = receivables(self.get_organization())
        context["customers"] = customers
        context["total_debt"] = total
        return context


class DebtAgeingView(ReportMixin, TemplateView):
    """
    Per-customer ageing of what they owe.

    Buckets: current (not yet due), 1–30 days overdue, 31–60, 61+. Plus
    a `prior_or_opening` column for opening balances and any unallocated
    payments, so each row reconciles against customer.outstanding_balance.
    """
    template_name = "reports/debt_ageing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = finance.debt_ageing(self.get_organization())

        totals = {
            "current": sum((r["current"] for r in rows), finance.ZERO),
            "1_30": sum((r["1_30"] for r in rows), finance.ZERO),
            "31_60": sum((r["31_60"] for r in rows), finance.ZERO),
            "61_plus": sum((r["61_plus"] for r in rows), finance.ZERO),
            "prior_or_opening": sum(
                (r["prior_or_opening"] for r in rows), finance.ZERO,
            ),
            "total_owed": sum((r["total_owed"] for r in rows), finance.ZERO),
        }

        context["rows"] = rows
        context["totals"] = totals
        return context


class SalesReportView(ReportMixin, TemplateView):
    template_name = "reports/sales_report.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        form = SalesReportForm(self.request.GET or None)
        context["form"] = form

        if form.is_valid():
            month = int(form.cleaned_data["month"])
            year = int(form.cleaned_data["year"])
            limit = int(form.cleaned_data["limit"])
            start, end = month_bounds(year, month)

            top_products = (
                SaleItem.objects.filter(
                    sale__organization=organization,
                    sale__created_at__date__range=(start, end),
                )
                .values("product__name")
                .annotate(
                    total_quantity=Sum("quantity"),
                    total_revenue=Sum(F("quantity") * F("unit_price")),
                )
                .order_by("-total_revenue")[:limit]
            )

            revenue_by_customer = (
                Sale.objects.filter(
                    organization=organization,
                    created_at__date__range=(start, end),
                )
                .exclude(customer__isnull=True)
                .values("customer__name")
                .annotate(total_spent=Sum("total"))
                .order_by("-total_spent")[:limit]
            )

            total_sales_revenue = (
                Sale.objects.filter(
                    organization=organization,
                    created_at__date__range=(start, end),
                ).aggregate(t=Sum("total"))["t"] or 0
            )
            total_transactions = Sale.objects.filter(
                organization=organization,
                created_at__date__range=(start, end),
            ).count()

            context.update({
                "top_products": top_products,
                "revenue_by_customer": revenue_by_customer,
                "total_sales_revenue": total_sales_revenue,
                "total_transactions": total_transactions,
                "month": month, "year": year, "limit": limit,
            })
        return context


class ExpenseTrendView(ReportMixin, TemplateView):
    template_name = "reports/expense_trends.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.get_organization()
        form = YearForm(self.request.GET or None)
        context["form"] = form

        if form.is_valid():
            year = int(form.cleaned_data["year"])
            monthly = (
                Expense.objects.filter(organization=org, date__year=year)
                .annotate(month=ExtractMonth("date"))
                .values("month")
                .annotate(total=Sum("amount"))
                .order_by("month")
            )
            totals = {row["month"]: row["total"] for row in monthly}
            months_data = [totals.get(m, 0) for m in range(1, 13)]
            yearly_total = sum(months_data)
            now = today()
            elapsed = 12 if year != now.year else now.month
            average = yearly_total / elapsed if yearly_total else 0

            with_data = [(m, v) for m, v in enumerate(months_data, start=1) if v > 0]
            if with_data:
                max_idx, max_val = max(with_data, key=lambda x: x[1])
                min_idx, min_val = min(with_data, key=lambda x: x[1])
            else:
                max_idx = max_val = min_idx = min_val = None

            context.update({
                "year": year,
                "months_data": months_data,
                "months": [
                    {"index": i, "name": calendar.month_abbr[i], "amount": months_data[i - 1]}
                    for i in range(1, 13)
                ],
                "yearly_total": yearly_total,
                "average": average,
                "max_month": max_idx, "max_value": max_val,
                "min_month": min_idx, "min_value": min_val,
                "max_month_name": calendar.month_abbr[max_idx] if max_idx else "",
                "min_month_name": calendar.month_abbr[min_idx] if min_idx else "",
            })
        return context


class ExportBusinessOverviewPDFView(ReportMixin, View):
    def get(self, request):
        org = self.get_organization()
        now = today()
        start = now.replace(day=1)
        f = period_figures(org, start, now)

        title = "Business Overview"
        subtitle = f"{start.strftime('%d %b %Y')} - {now.strftime('%d %b %Y')}"
        headers = ["Metric", "Value"]
        rows = [
            ["Revenue", f"MK {f['revenue']:,.2f}"],
            ["Cash in", f"MK {f['cash_in']:,.2f}"],
            ["Cash out", f"MK {f['cash_out']:,.2f}"],
            ["Net profit", f"MK {f['net_profit']:,.2f}"],
        ]
        kpis = {
            "Revenue": f"MK {f['revenue']:,.2f}",
            "Net cash": f"MK {f['net_cash']:,.2f}",
            "Net profit": f"MK {f['net_profit']:,.2f}",
        }
        return services.generate_pdf_response(
            "business_overview", title, subtitle, headers, rows, kpis,
        )


def _pl_rows(f):
    return [
        ["Revenue", f["revenue"]],
        ["Cost of goods sold", f["cogs"]],
        ["Gross profit", f["gross_profit"]],
        ["Expenses", f["expenses"]],
        ["Net profit", f["net_profit"]],
    ]


def _pl_parse_or_400(request):
    now = today()
    month = _int_or(request.GET.get("month"), now.month)
    year = _int_or(request.GET.get("year"), now.year)
    if not (1 <= month <= 12 and 2020 <= year <= now.year + 1):
        return None
    return month, year


class ExportProfitLossPDFView(ReportMixin, View):
    def get(self, request):
        parsed = _pl_parse_or_400(request)
        if parsed is None:
            return HttpResponseBadRequest("Invalid period")
        month, year = parsed
        start, end = month_bounds(year, month)
        f = period_figures(self.get_organization(), start, end)
        title = "Profit & Loss Statement"
        subtitle = f"{calendar.month_name[month]} {year}"
        headers = ["Category", "Amount"]
        rows = [[name, f"MK {val:,.2f}"] for name, val in _pl_rows(f)]
        return services.generate_pdf_response(
            f"profit_loss_{month}_{year}", title, subtitle, headers, rows,
        )


class ExportProfitLossExcelView(ReportMixin, View):
    def get(self, request):
        parsed = _pl_parse_or_400(request)
        if parsed is None:
            return HttpResponseBadRequest("Invalid period")
        month, year = parsed
        start, end = month_bounds(year, month)
        f = period_figures(self.get_organization(), start, end)
        title = f"Profit & Loss - {calendar.month_name[month]} {year}"
        headers = ["Category", "Amount"]
        rows = _pl_rows(f)
        return services.generate_excel_response(
            f"profit_loss_{month}_{year}", title, headers, rows,
        )