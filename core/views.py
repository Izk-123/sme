# core/views.py
from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import F, Sum
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.generic import TemplateView, View

from customers.models import Customer
from expenses.models import Expense
from sales.models import Product, Sale, SaleItem


def _month_sequence(end_date, months_back):
    """
    Real calendar-month arithmetic instead of `today - timedelta(days=i*30)`,
    which drifts against actual month boundaries (30 != 1 calendar month)
    and gets worse the further back you go. Returns [(year, month), ...]
    oldest-first, `months_back` months before end_date through end_date.
    """
    sequence = []
    year, month = end_date.year, end_date.month
    for i in range(months_back, -1, -1):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        sequence.append((y, m))
    return sequence


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        membership = self.request.membership
        role = membership.role.slug if membership and membership.role_id else None
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)

        # ---------- ROLE LINKS ----------
        ROLE_LINKS = {
            "owner": [
                ("record_sale", "Record Sale"),
                ("receive_stock", "Receive Stock"),
                ("stock_valuation", "Stock Valuation"),
                ("expense_list", "Expenses"),
                ("profit_loss", "Profit & Loss"),
                ("sales_report", "Sales Report"),
                ("expense_trends", "Expense Trends"),
                ("team_list", "Manage Team"),
                ("supplier_list", "Suppliers"),
                ("customer_list", "Customers"),
            ],
            "cashier": [("record_sale", "Record Sale")],
            "stock_clerk": [
                ("receive_stock", "Receive Stock"),
                ("stock_valuation", "Stock Valuation"),
            ],
            "accountant": [
                ("stock_valuation", "Stock Valuation"),
                ("expense_list", "Expenses"),
                ("profit_loss", "Profit & Loss"),
                ("sales_report", "Sales Report"),
                ("expense_trends", "Expense Trends"),
                ("supplier_list", "Suppliers"),
                ("customer_list", "Customers"),
            ],
        }

        if not org:
            context.update({"links": ROLE_LINKS.get(role, []), "role": role})
            return context

        # ---------- KPIs ----------
        today_sales = Sale.objects.filter(
            organization=org, created_at__date=today
        ).aggregate(total=Sum('total'))['total'] or 0

        yesterday_sales = Sale.objects.filter(
            organization=org, created_at__date=yesterday
        ).aggregate(total=Sum('total'))['total'] or 0

        if yesterday_sales:
            sales_change = ((today_sales - yesterday_sales) / yesterday_sales) * 100
        else:
            sales_change = 0

        sales_progress = 0
        if yesterday_sales > 0:
            sales_progress = min((today_sales / yesterday_sales) * 50, 100)

        today_expenses = Expense.objects.filter(
            organization=org, date=today
        ).aggregate(total=Sum('amount'))['total'] or 0

        gross_profit = today_sales - today_expenses

        stock_value = Product.objects.filter(
            organization=org
        ).aggregate(total=Sum(F('price') * F('stock_quantity')))['total'] or 0

        customer_count = Customer.objects.filter(organization=org).count()

        # ---------- SALES TREND (last 7 days) ----------
        sales_trend = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            total = Sale.objects.filter(
                organization=org, created_at__date=day
            ).aggregate(total=Sum('total'))['total'] or 0
            sales_trend.append(total)

        max_trend = max(sales_trend) if sales_trend else 1
        trend_points = []
        for i, val in enumerate(sales_trend):
            x = (i / 6) * 300
            y = 100 - (val / max_trend * 100) if max_trend else 100
            trend_points.append(f"{x},{y}")
        trend_polyline = " ".join(trend_points)

        # ---------- REVENUE vs EXPENSES (last 6 months, real calendar months) ----------
        months = []
        revenue_data = []
        expense_data = []
        for year, month in _month_sequence(today, 5):
            revenue = Sale.objects.filter(
                organization=org, created_at__year=year, created_at__month=month
            ).aggregate(total=Sum('total'))['total'] or 0
            expenses = Expense.objects.filter(
                organization=org, date__year=year, date__month=month
            ).aggregate(total=Sum('amount'))['total'] or 0
            months.append(str(month))
            revenue_data.append(revenue)
            expense_data.append(expenses)

        max_revenue = max(revenue_data) if revenue_data else 1
        max_expense = max(expense_data) if expense_data else 1
        revenue_percentages = [(r / max_revenue * 100) if max_revenue else 0 for r in revenue_data]
        expense_percentages = [(e / max_expense * 100) if max_expense else 0 for e in expense_data]

        chart_data = []
        for i in range(len(months)):
            chart_data.append({
                'month': months[i],
                'revenue_percent': revenue_percentages[i],
                'expense_percent': expense_percentages[i],
            })

        # ---------- TOP PRODUCTS ----------
        top_products = SaleItem.objects.filter(
            sale__organization=org
        ).values(
            'product__name'
        ).annotate(
            total_quantity=Sum('quantity'),
            total_revenue=Sum(F('quantity') * F('unit_price'))
        ).order_by('-total_revenue')[:5]

        # ---------- ALERTS ----------
        low_stock_products = Product.objects.filter(
            organization=org,
            stock_quantity__lte=F('low_stock_threshold')
        )

        overdue_customers = Customer.objects.filter(
            organization=org,
            outstanding_balance__gt=0
        ).order_by('-outstanding_balance')[:5]

        recent_sales = Sale.objects.filter(
            organization=org
        ).order_by('-created_at')[:5]

        context.update({
            "today_sales": today_sales,
            "today_expenses": today_expenses,
            "gross_profit": gross_profit,
            "stock_value": stock_value,
            "customer_count": customer_count,
            "sales_change": sales_change,
            "sales_progress": sales_progress,
            "sales_trend": sales_trend,
            "trend_polyline": trend_polyline,
            "chart_data": chart_data,
            "top_products": top_products,
            "low_stock_products": low_stock_products,
            "overdue_customers": overdue_customers,
            "recent_sales": recent_sales,
            "links": ROLE_LINKS.get(role, []),
            "role": role,
        })
        return context


class DashboardKPIPartialView(LoginRequiredMixin, TemplateView):
    """HTMX endpoint that returns *only* the KPI cards, polled every 30s."""

    template_name = "core/_kpi_cards.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.request.organization
        today = timezone.now().date()

        if not organization:
            context.update({"today_sales": 0, "today_expenses": 0, "gross_profit": 0, "stock_value": 0})
            return context

        today_sales = Sale.objects.filter(
            organization=organization, created_at__date=today
        ).aggregate(total=Sum('total'))['total'] or 0

        today_expenses = Expense.objects.filter(
            organization=organization, date=today
        ).aggregate(total=Sum('amount'))['total'] or 0

        gross_profit = today_sales - today_expenses

        stock_value = Product.objects.filter(
            organization=organization
        ).aggregate(total=Sum(F('price') * F('stock_quantity')))['total'] or 0

        context.update({
            "today_sales": today_sales,
            "today_expenses": today_expenses,
            "gross_profit": gross_profit,
            "stock_value": stock_value,
        })
        return context


class ActionMenuView(LoginRequiredMixin, TemplateView):
    template_name = "core/action_menu.html"


class MoreMenuView(LoginRequiredMixin, TemplateView):
    template_name = "core/more_menu.html"


class OnboardingWizardView(LoginRequiredMixin, TemplateView):
    template_name = "core/onboarding/wizard.html"

    def get(self, request, *args, **kwargs):
        # Guard against org being None (e.g. a superuser with no
        # Membership yet) - request.user.organization.enabled_modules
        # used to crash here with AttributeError.
        org = request.organization
        if org and org.enabled_modules:
            return redirect("home")
        return super().get(request, *args, **kwargs)


class OnboardingStepView(LoginRequiredMixin, View):
    def get(self, request, step):
        context = {}
        if step == 5:
            # Set by step 4 below, popped once so a page refresh can't re-show it.
            context["invite_link"] = request.session.pop("onboarding_invite_link", None)
        return render(request, f"core/onboarding/step_{step}.html", context)

    def post(self, request, step):
        org = request.organization
        if not org:
            return redirect("home")

        step_context = {}

        if step == 1:
            business_type = request.POST.get("business_type")
            # Validate against the real choices - previously any string
            # from the POST body was written straight through.
            if business_type in dict(org.BUSINESS_TYPES):
                org.business_type = business_type
                org.save(update_fields=["business_type"])
        elif step == 2:
            business_size = request.POST.get("business_size")
            if business_size in dict(org.SIZE_CHOICES):
                org.business_size = business_size
                org.save(update_fields=["business_size"])
        elif step == 3:
            modules = request.POST.getlist("modules")
            org.enabled_modules = modules
            org.save(update_fields=["enabled_modules"])
        elif step == 4:
            # Optional: create a real Invitation, same as the Team page's
            # InviteEmployeeView - see accounts.models.Invitation. Silently
            # skipped if left blank, since this step is optional ("Skip").
            full_name = request.POST.get("full_name", "").strip()
            role_slug = request.POST.get("role", "")
            if full_name and role_slug:
                from django.db.models import Q
                from django.urls import reverse

                from accounts.models import Invitation, Role

                role = (
                    Role.objects.filter(Q(organization__isnull=True) | Q(organization=org), slug=role_slug)
                    .exclude(slug="owner")
                    .first()
                )
                if role:
                    invitation = Invitation.objects.create(
                        organization=org,
                        role=role,
                        invited_by=request.user,
                        full_name=full_name,
                        phone_number=request.POST.get("phone_number", "").strip(),
                    )
                    request.session["onboarding_invite_link"] = request.build_absolute_uri(
                        reverse("accept_invitation", kwargs={"token": invitation.token})
                    )
        elif step == 5:
            return redirect("home")

        next_step = step + 1
        if next_step > 5:
            return redirect("home")
        if next_step == 5:
            step_context["invite_link"] = request.session.pop("onboarding_invite_link", None)
        return render(request, f"core/onboarding/step_{next_step}.html", step_context)
