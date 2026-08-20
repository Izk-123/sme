# core/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="home"),
    path("dashboard/kpis/", views.DashboardKPIPartialView.as_view(), name="dashboard_kpis"),
    path("action-menu/", views.ActionMenuView.as_view(), name="action_menu"),
    path("more/", views.MoreMenuView.as_view(), name="more_menu"),
    # Onboarding
    path("onboarding/", views.OnboardingWizardView.as_view(), name="onboarding"),
    path("onboarding/step/<int:step>/", views.OnboardingStepView.as_view(), name="onboarding_step"),
]