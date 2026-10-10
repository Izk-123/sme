from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView, View

from core.permissions import OrganizationMixin, RoleRequiredMixin

from .models import SubscriptionPlan
from .services import can_downgrade_to, check_usage_limits, get_subscription, upgrade_plan


class SubscriptionMixin(LoginRequiredMixin, RoleRequiredMixin, OrganizationMixin):
    """Owner-only, same pattern as accounts.views.TeamMixin - managing
    the subscription is a business-level decision, not something any
    team member should be able to change."""

    allowed_roles = ["owner"]


class PlansView(SubscriptionMixin, TemplateView):
    template_name = "subscriptions/plans.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["plans"] = SubscriptionPlan.objects.filter(is_active=True)
        context["subscription"] = get_subscription(self.get_organization())
        return context


class SubscriptionDetailView(SubscriptionMixin, TemplateView):
    template_name = "subscriptions/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        subscription = get_subscription(organization)
        context["subscription"] = subscription
        context["usage_warnings"] = check_usage_limits(organization)
        context["invoices"] = subscription.invoices.all()[:10]
        return context


class UpgradePlanView(SubscriptionMixin, View):
    template_name = "subscriptions/upgrade.html"

    def get(self, request):
        from django.shortcuts import render

        organization = self.get_organization()
        current = get_subscription(organization)
        plans = SubscriptionPlan.objects.filter(is_active=True).exclude(pk=current.plan_id)
        return render(request, self.template_name, {"current_subscription": current, "plans": plans})

    def post(self, request):
        organization = self.get_organization()
        current = get_subscription(organization)
        new_plan = get_object_or_404(SubscriptionPlan, pk=request.POST.get("plan"), is_active=True)

        is_downgrade = new_plan.price_monthly < current.plan.price_monthly
        if is_downgrade:
            allowed, reasons = can_downgrade_to(organization, new_plan)
            if not allowed:
                for reason in reasons:
                    messages.error(request, reason)
                messages.error(request, f"Reduce usage below {new_plan.name}'s limits before downgrading.")
                return redirect("upgrade_plan")

        if new_plan.price_monthly <= 0:
            # Free plan - no payment to collect, switch immediately.
            upgrade_plan(organization, new_plan)
            messages.success(request, f"Switched to the {new_plan.name} plan.")
            return redirect("subscription_detail")

        # Any paid plan goes through real checkout - see payments/views.py.
        # Nothing is activated here; activation happens once
        # payments.services.verify_and_apply() confirms the payment with
        # PayChangu directly (never from this request alone).
        from django.urls import reverse
        return redirect(f"{reverse('initiate_subscription_checkout')}?plan={new_plan.pk}")
