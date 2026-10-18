# core/views.py
"""
Dashboard, action menus, and the onboarding wizard.

The two most delicate pieces here are:

  * DashboardView — role-gated links, KPI aggregation, trend data.
    Nothing surprising structurally, but easy to N+1 or to leave a
    query unbounded once the org has real data. Read the comments on
    the individual queries if you touch them.

  * OnboardingStepView — advances the owner through the wizard and,
    on the final step, flips Organization.onboarding_completed so
    nothing sends them back here. That flag is read by three separate
    places (this view, OnboardingWizardView, and
    accounts.views.PostLoginRouterView) and they must all agree about
    what "finished" means — hence the dedicated field instead of
    inferring completion from enabled_modules.

First-login guidance is the other major concern:

  * Welcome modal (3 slides, shown once at first login, dismissible).

  * "Get started" checklist on the dashboard that ticks itself off
    from real business data (products, costs, sales, customers,
    expenses, staff). Built by core.getting_started.build_checklist.

  * GetStartedActionView handles all three actions the user can take
    on this guidance: mark the tour seen, dismiss the checklist, or
    restart both from the header's "Show welcome guide" menu item.

The design (per the product spec) is deliberately NOT a spotlight
tour: on a small phone the sidebar collapses and highlighted buttons
end up off-screen. A checklist with big buttons that open the right
page works on any screen and teaches by doing.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import F, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.generic import TemplateView, View

from accounts.models import UserPreference
from core.permissions import SubscriptionWriteRequiredMixin
from customers.models import Customer
from expenses.models import Expense
from organizations.models import Organization
from sales.models import Product, Sale, SaleItem
from subscriptions.models import SubscriptionPlan

from .getting_started import build_checklist


# =============================================================================
# Helpers
# =============================================================================

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


# =============================================================================
# Dashboard
# =============================================================================

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        membership = self.request.membership
        role = membership.role.slug if membership and membership.role_id else None
        today = timezone.localdate()
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

        # Early return for users with no organization (e.g. a superuser
        # without a Membership yet). Nothing below this depends on the org
        # being present, so the guard must sit *before* any org-scoped query.
        #
        # show_welcome is explicitly False here: the welcome modal's
        # content (esp. slide 2, which talks about owner/cashier roles
        # and inventory) is meaningless without an organization, and
        # showing it would burn tour_seen before the user has a
        # business to be welcomed into.
        if not org:
            context.update({
                "links": ROLE_LINKS.get(role, []),
                "role": role,
                "products_missing_cost": 0,
                "show_welcome": False,
            })
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

        # ---------- PRODUCTS MISSING A COST PRICE ----------
        # Feeds the dashboard warning banner. A product with cost_price=None
        # or 0 makes gross-profit figures wrong until it's filled in.
        products_missing_cost = Product.objects.filter(
            organization=org
        ).filter(
            Q(cost_price__isnull=True) | Q(cost_price=0)
        ).count()

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

        # ---------- FIRST-LOGIN GUIDANCE ----------
        #
        # show_welcome fires once per user, regardless of role, because
        # every role benefits from the intro. The *content* of slide 2
        # adapts per role in the template, but the "you haven't seen this
        # yet" check is the same flag for everyone.
        #
        # The checklist is owner-only: cashiers and stock clerks have a
        # single job each (see slide 2), and putting a "add products,
        # add customers, record an expense" checklist in front of them
        # just adds noise to a screen that isn't theirs to complete.
        # Dismissing the checklist on the owner's dashboard must not
        # affect anyone else's, so the flag lives on UserPreference
        # (user-scoped), not on Organization.
        pref, _ = UserPreference.objects.get_or_create(user=self.request.user)
        context["show_welcome"] = not pref.tour_seen

        if role == "owner" and not pref.getting_started_dismissed:
            checklist = build_checklist(org)
            # An all_done checklist is redundant noise — hide it. It
            # will re-appear only if the user restarts the tour via
            # the header menu, at which point getting_started_dismissed
            # is reset to False and the (still all-done) checklist
            # would render... except the build_checklist result will
            # also be all_done and thus suppressed. That's intentional:
            # restart brings back the welcome modal, which is what most
            # users mean by "show me the guide again".
            if not checklist["all_done"]:
                context["checklist"] = checklist

        context.update({
            "today_sales": today_sales,
            "today_expenses": today_expenses,
            "gross_profit": gross_profit,
            "stock_value": stock_value,
            "products_missing_cost": products_missing_cost,
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
        today = timezone.localdate()

        if not organization:
            context.update({
                "today_sales": 0,
                "today_expenses": 0,
                "gross_profit": 0,
                "stock_value": 0,
            })
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


# =============================================================================
# Action menus
# =============================================================================

class ActionMenuView(LoginRequiredMixin, TemplateView):
    template_name = "core/action_menu.html"


class MoreMenuView(LoginRequiredMixin, TemplateView):
    template_name = "core/more_menu.html"


# =============================================================================
# First-login guidance actions
# =============================================================================

class GetStartedActionView(LoginRequiredMixin, View):
    """
    One POST endpoint behind every button/link that mutates the
    first-login guidance flags:

        tour-seen  →  welcome modal finished, skipped, or closed.
                      Fired via fetch() from the modal's
                      `hidden.bs.modal` handler so it fires in every
                      terminal case — not just the "Let's start" button.

        dismiss    →  "Hide" on the dashboard checklist.

        restart    →  "Show welcome guide" in the header dropdown.
                      Brings BOTH the welcome modal and the checklist
                      back by resetting both flags.

    Responds with HTTP 204 (no content) when called by fetch(), and a
    redirect to the dashboard otherwise. That split lets the modal's
    JS call this without touching the page, while a plain form submit
    (dismiss / restart) behaves like a normal navigation.
    """

    # Central map of action → field changes. Adding a new action is a
    # one-line change here; adding a new field is a one-line change in
    # every dict that needs to touch it.
    ACTIONS = {
        "tour-seen": {"tour_seen": True},
        "dismiss":   {"getting_started_dismissed": True},
        "restart":   {"tour_seen": False, "getting_started_dismissed": False},
    }

    def post(self, request, action):
        changes = self.ACTIONS.get(action)
        if changes is None:
            # An unrecognised action is a client bug or a probe —
            # treat it like a missing resource rather than silently
            # no-op'ing. The URL itself is stable; only `action` is
            # variable.
            raise Http404

        pref, _ = UserPreference.objects.get_or_create(user=request.user)
        for field, value in changes.items():
            setattr(pref, field, value)
        # update_fields is the exact set of fields we just mutated —
        # keeps the UPDATE statement tight and avoids racing the
        # auto_now/auto_now_add fields if any get added later.
        pref.save(update_fields=list(changes))

        if request.headers.get("X-Requested-With") == "fetch":
            # The welcome modal's JS only needs to know the call
            # succeeded — no body, no redirect.
            return HttpResponse(status=204)
        return redirect("home")


# =============================================================================
# Onboarding wizard
# =============================================================================

class OnboardingWizardView(LoginRequiredMixin, TemplateView):
    """
    Landing page for the wizard. Its only job is to redirect users who
    have already finished it — everyone else falls through to step 1,
    which the wizard template renders.

    The completion check reads `Organization.onboarding_completed`, NOT
    `enabled_modules`. The old check would loop anyone who finished the
    wizard without selecting any modules back into step 1 on every
    login, because `enabled_modules == []` and "not onboarded" were
    indistinguishable. See the field docstring in organizations/models.py
    for why those two signals are deliberately separate.
    """

    template_name = "core/onboarding/wizard.html"

    def get(self, request, *args, **kwargs):
        org = request.organization
        # `org` can legitimately be None for a superuser with no
        # Membership. Fall through to the wizard in that case — it's
        # harmless and better than an error page.
        if org and org.onboarding_completed:
            return redirect("home")
        return super().get(request, *args, **kwargs)


class OnboardingStepView(LoginRequiredMixin, SubscriptionWriteRequiredMixin, View):
    """
    Drives the multi-step wizard. Each POST handles the data for the
    step it was called on, then renders (or redirects to) the next step.

    Steps, in order:
        1  Business type
        2  Business size
        3  Enabled modules
        4  Invite the first employee (optional — "Skip" leaves it blank)
        5  Summary / "you're all set"

    The key side effect is on step 5's POST: flipping
    Organization.onboarding_completed to True. That's what stops
    OnboardingWizardView and accounts.views.PostLoginRouterView from
    sending the user back here.

    Both GET and POST refuse to run once the flag is set, so a stale
    bookmark or a browser Back button can't drop a finished user into
    an old step.
    """

    def get(self, request, step):
        # Defensive: if the wizard is already done, don't let a stale
        # bookmark re-open it. The check reads the same flag the wizard
        # landing page and the post-login router read, so all three
        # agree about what "finished" means.
        org = request.organization
        if org and org.onboarding_completed:
            return redirect("home")

        context = {}
        if step == 5:
            # Set by step 4 below, popped once so a page refresh can't
            # re-show it. (Step 4's invite is optional, so this is often
            # None — that's fine, the template handles it.)
            context["invite_link"] = request.session.pop("onboarding_invite_link", None)
        return render(request, f"core/onboarding/step_{step}.html", context)

    def post(self, request, step):
        org = request.organization
        if not org:
            # No org to onboard — a superuser without a Membership,
            # most likely. Nothing sensible to do here but send them
            # home, where the ROLE_LINKS early-return handles it.
            return redirect("home")

        # Same defensive check as GET above. If the wizard is already
        # finished, ignore a straggling POST (double-submit, bookmark
        # replay, etc.) and send the user to the dashboard.
        if org.onboarding_completed:
            return redirect("home")

        step_context = {}

        if step == 1:
            business_type = request.POST.get("business_type")
            # Validate against the real choices — previously any string
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
            # InviteEmployeeView — see accounts.models.Invitation.
            # Silently skipped if left blank, since this step is optional
            # ("Skip"). The generated link is stashed in the session so
            # step 5 can display it once.
            full_name = request.POST.get("full_name", "").strip()
            role_slug = request.POST.get("role", "")
            if full_name and role_slug:
                from django.urls import reverse

                from accounts.models import Invitation, Role

                role = (
                    Role.objects
                    .filter(Q(organization__isnull=True) | Q(organization=org),
                            slug=role_slug)
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
            # Final step. Mark the org as onboarded, then send the owner
            # to the dashboard. From this point on:
            #   * OnboardingWizardView.get() redirects here.
            #   * PostLoginRouterView.get() routes to /dashboard/.
            #   * This view's GET and POST both bail out above.
            # All four checks read the same flag, so they can't disagree.
            org.onboarding_completed = True
            org.save(update_fields=["onboarding_completed"])
            return redirect("home")

        # Advance to the next step. Steps 1–4 fall through to here with
        # a plain render; step 5 never reaches this point because it
        # returned above.
        next_step = step + 1
        if next_step > 5:
            return redirect("home")
        if next_step == 5:
            step_context["invite_link"] = request.session.pop("onboarding_invite_link", None)
        return render(request, f"core/onboarding/step_{next_step}.html", step_context)


# =============================================================================
# Public landing page
# =============================================================================

class LandingPageView(TemplateView):
    """
    Public landing page.

    - Logged-in users are redirected to the dashboard.
    - Anonymous visitors see the marketing page.
    - Subscription plans are loaded from the DB (so pricing changes in
      /admin/ reflect on the landing page automatically).
    - A small set of live stats are shown (business count, etc.) so the
      page feels alive without needing a full analytics pipeline.
    """
    template_name = "landing.html"

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("home")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["plans"] = (
            SubscriptionPlan.objects.filter(is_active=True)
            .order_by("sort_order", "price_monthly")
        )

        # Live stats — counts only, cheap queries. If you grow past
        # ~10k orgs, cache these for 10 minutes instead.
        context["business_count"] = Organization.objects.count()
        context["product_count"] = Product.objects.count()
        context["transaction_count"] = Sale.objects.count()

        return context