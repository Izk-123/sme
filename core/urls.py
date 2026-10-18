# core/urls.py
from django.urls import path

from . import views

urlpatterns = [
    # ---- Public landing ----
    path("", views.LandingPageView.as_view(), name="landing"),

    # ---- Dashboard ----
    path("dashboard/", views.DashboardView.as_view(), name="home"),
    path("dashboard/kpis/", views.DashboardKPIPartialView.as_view(), name="dashboard_kpis"),

    # ---- Action menus ----
    path("action-menu/", views.ActionMenuView.as_view(), name="action_menu"),
    path("more/", views.MoreMenuView.as_view(), name="more_menu"),

    # ---- First-login guidance actions ----
    # One endpoint, three actions, all POST-only:
    #   tour-seen  →  welcome modal closed (via fetch, returns 204)
    #   dismiss    →  "Hide" on the dashboard checklist
    #   restart    →  "Show welcome guide" in the header dropdown
    #
    # See core.views.GetStartedActionView. The URL is stable; only
    # `action` varies, which is why a <str:action> converter is used
    # rather than three separate paths.
    path(
        "get-started/<str:action>/",
        views.GetStartedActionView.as_view(),
        name="get_started_action",
    ),

    # ---- Onboarding wizard ----
    path("onboarding/", views.OnboardingWizardView.as_view(), name="onboarding"),
    path("onboarding/step/<int:step>/", views.OnboardingStepView.as_view(), name="onboarding_step"),
]