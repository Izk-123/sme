from django.urls import path

from . import views

urlpatterns = [
    path("plans/", views.PlansView.as_view(), name="plans"),
    path("", views.SubscriptionDetailView.as_view(), name="subscription_detail"),
    path("upgrade/", views.UpgradePlanView.as_view(), name="upgrade_plan"),
]
