# reports/views.py
"""
Views for the Reports app.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models.functions import ExtractMonth
from django.db.models import Sum, F
from django.utils import timezone
from django.shortcuts import render
from django.views.generic import TemplateView
from django.views import View

from core.permissions import OrganizationMixin, RoleRequiredMixin
from expenses.models import Expense
from sales.models import Sale, SaleItem
from customers.models import Customer

from .forms import MonthYearForm, SalesReportForm, YearForm
from . import services  # all functions are in services.py


# =============================================================================
# Reports Hub (Index)
# =============================================================================

class ReportIndexView(LoginRequiredMixin, OrganizationMixin, TemplateView):
    template_name = "reports/index.html"


# =============================================================================
# Business Overview
# =============================================================================

class BusinessPerformanceView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    allowed_roles = ["owner", "accountant"]
    template_name = "reports/business_performance.html"

    def get(self, request):
        org = self.get_organization()
        today = timezone.now().date()
        start_date = today.replace(day=1)
        last_month_end = start_date - timezone.timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        current = services.get_business_kpis(org, start_date, today)
        previous = services.get_business_kpis(org, last_month_start, last_month_end)

        def calc_change(cur, prev):
            if prev == 0:
                return 0
            return round(((cur - prev) / prev) * 100, 1)

        context = {
            'current': current,
            'previous': previous,
            'change': {
                'sales': calc_change(current['total_sales'], previous['total_sales']),
                'expenses': calc_change(current['total_expenses'], previous['total_expenses']),
                'profit': calc_change(current['gross_profit'], previous['gross_profit']),
            }
        }
        return render(request, self.template_name, context)


# =============================================================================
# Inventory Stock Report
# =============================================================================

class InventoryStockView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    allowed_roles = ["owner", "stock_clerk", "accountant"]
    template_name = "reports/inventory_stock.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.get_organization()
        products = services.get_current_stock(org)
        context['products'] = products
        context['low_stock'] = services.get_low_stock(org)
        total = sum(p.total_value for p in products)
        context['total_value'] = total
        return context


# =============================================================================
# Customer Debt Report
# =============================================================================

class CustomerDebtView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    allowed_roles = ["owner", "accountant"]
    template_name = "reports/customer_debt.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.get_organization()
        customers = services.get_customer_debt(org)
        context['customers'] = customers
        context['total_debt'] = sum(c.outstanding_balance for c in customers)
        return context


# =============================================================================
# Profit & Loss (Existing)
# =============================================================================

class ProfitLossView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    allowed_roles = ["owner", "accountant"]
    template_name = "reports/profit_loss.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        form = MonthYearForm(self.request.GET or None)
        context["form"] = form

        if form.is_valid():
            month = int(form.cleaned_data["month"])
            year = int(form.cleaned_data["year"])

            revenue = Sale.objects.filter(
                organization=organization,
                created_at__year=year,
                created_at__month=month
            ).aggregate(total=Sum('total'))['total'] or 0

            expenses = Expense.objects.filter(
                organization=organization,
                date__year=year,
                date__month=month
            ).aggregate(total=Sum('amount'))['total'] or 0

            context.update({
                "revenue": revenue,
                "expenses": expenses,
                "net_profit": revenue - expenses,
                "month": month,
                "year": year,
            })
        return context


# =============================================================================
# Sales Report (Existing)
# =============================================================================

class SalesReportView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    allowed_roles = ["owner", "accountant"]
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

            top_products = SaleItem.objects.filter(
                sale__organization=organization,
                sale__created_at__year=year,
                sale__created_at__month=month
            ).values('product__name').annotate(
                total_quantity=Sum('quantity'),
                total_revenue=Sum(F('quantity') * F('unit_price'))
            ).order_by('-total_revenue')[:limit]

            revenue_by_customer = Sale.objects.filter(
                organization=organization,
                created_at__year=year,
                created_at__month=month
            ).exclude(customer__isnull=True).values('customer__name').annotate(
                total_spent=Sum('total')
            ).order_by('-total_spent')[:limit]

            total_sales_revenue = Sale.objects.filter(
                organization=organization,
                created_at__year=year,
                created_at__month=month
            ).aggregate(total=Sum('total'))['total'] or 0

            total_transactions = Sale.objects.filter(
                organization=organization,
                created_at__year=year,
                created_at__month=month
            ).count()

            context.update({
                "top_products": top_products,
                "revenue_by_customer": revenue_by_customer,
                "total_sales_revenue": total_sales_revenue,
                "total_transactions": total_transactions,
                "month": month,
                "year": year,
                "limit": limit,
            })
        return context


# =============================================================================
# Expense Trends (Existing)
# =============================================================================

class ExpenseTrendView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, TemplateView):
    allowed_roles = ["owner", "accountant"]
    template_name = "reports/expense_trends.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        form = YearForm(self.request.GET or None)
        context["form"] = form

        if form.is_valid():
            year = int(form.cleaned_data["year"])

            monthly_data = Expense.objects.filter(
                organization=organization,
                date__year=year
            ).annotate(month=ExtractMonth('date')).values('month').annotate(
                total=Sum('amount')
            ).order_by('month')

            month_totals = {item['month']: item['total'] for item in monthly_data}
            months_data = [month_totals.get(m, 0) for m in range(1, 13)]

            yearly_total = sum(months_data)
            average = yearly_total / 12 if yearly_total > 0 else 0

            if yearly_total > 0:
                max_month_idx, max_value = max(
                    enumerate(months_data, start=1),
                    key=lambda x: x[1]
                )
                min_month_idx, min_value = min(
                    enumerate(months_data, start=1),
                    key=lambda x: x[1]
                )
            else:
                max_month_idx = max_value = min_month_idx = min_value = None

            context.update({
                "year": year,
                "months_data": months_data,
                "yearly_total": yearly_total,
                "average": average,
                "max_month": max_month_idx,
                "max_value": max_value,
                "min_month": min_month_idx,
                "min_value": min_value,
            })
        return context


# =============================================================================
# EXPORT VIEWS (PDF & Excel)
# =============================================================================

class ExportBusinessOverviewPDFView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    allowed_roles = ["owner", "accountant"]
    
    def get(self, request):
        org = self.get_organization()
        today = timezone.now().date()
        start_date = today.replace(day=1)
        last_month_end = start_date - timezone.timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        current = services.get_business_kpis(org, start_date, today)

        title = "Business Overview"
        subtitle = f"{start_date.strftime('%d %b %Y')} - {today.strftime('%d %b %Y')}"
        headers = ["Metric", "Value"]
        rows = [
            ["Total Sales", f"MK {current['total_sales']:,.2f}"],
            ["Total Expenses", f"MK {current['total_expenses']:,.2f}"],
            ["Gross Profit", f"MK {current['gross_profit']:,.2f}"],
            ["Cash Received", f"MK {current['cash_received']:,.2f}"],
            ["Customer Credit", f"MK {current['customer_credit']:,.2f}"],
        ]
        kpis = {
            "Money In": f"MK {current['total_sales']:,.2f}",
            "Money Out": f"MK {current['total_expenses']:,.2f}",
            "Profit": f"MK {current['gross_profit']:,.2f}"
        }
        return services.generate_pdf_response("business_overview", title, subtitle, headers, rows, kpis)


class ExportProfitLossPDFView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    allowed_roles = ["owner", "accountant"]

    def get(self, request):
        org = self.get_organization()
        # Use `or` (not .get()'s default) so empty-string params (?month=&year=)
        # fall back to the current month/year instead of raising ValueError.
        month = int(request.GET.get('month') or timezone.now().month)
        year = int(request.GET.get('year') or timezone.now().year)

        revenue = Sale.objects.filter(
            organization=org, created_at__year=year, created_at__month=month
        ).aggregate(total=Sum('total'))['total'] or 0
        expenses = Expense.objects.filter(
            organization=org, date__year=year, date__month=month
        ).aggregate(total=Sum('amount'))['total'] or 0

        title = "Profit & Loss Statement"
        subtitle = f"{month}/{year}"
        headers = ["Category", "Amount"]
        rows = [
            ["Revenue (Money In)", f"MK {revenue:,.2f}"],
            ["Expenses (Money Out)", f"MK {expenses:,.2f}"],
            ["Net Profit", f"MK {revenue - expenses:,.2f}"],
        ]
        return services.generate_pdf_response(f"profit_loss_{month}_{year}", title, subtitle, headers, rows)


class ExportProfitLossExcelView(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin, View):
    allowed_roles = ["owner", "accountant"]

    def get(self, request):
        org = self.get_organization()
        # Use `or` (not .get()'s default) so empty-string params (?month=&year=)
        # fall back to the current month/year instead of raising ValueError.
        month = int(request.GET.get('month') or timezone.now().month)
        year = int(request.GET.get('year') or timezone.now().year)

        revenue = Sale.objects.filter(
            organization=org, created_at__year=year, created_at__month=month
        ).aggregate(total=Sum('total'))['total'] or 0
        expenses = Expense.objects.filter(
            organization=org, date__year=year, date__month=month
        ).aggregate(total=Sum('amount'))['total'] or 0

        title = "Profit & Loss"
        headers = ["Category", "Amount"]
        rows = [
            ["Revenue (Money In)", revenue],
            ["Expenses (Money Out)", expenses],
            ["Net Profit", revenue - expenses],
        ]
        return services.generate_excel_response(f"profit_loss_{month}_{year}", title, headers, rows)