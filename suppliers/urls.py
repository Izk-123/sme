# suppliers/urls.py
#
# Order note: literal prefixes ("add/", "payments/") must come before
# the <int:pk>/ catch-all, otherwise Django has no way to route them.
# Django tries patterns top-down and takes the first match.
from django.urls import path

from . import views

urlpatterns = [
    # ---- Suppliers ---------------------------------------------------
    path("", views.SupplierListView.as_view(), name="supplier_list"),
    path("add/", views.SupplierCreateView.as_view(), name="supplier_add"),
    path("<int:pk>/edit/", views.SupplierUpdateView.as_view(), name="supplier_edit"),
    path("<int:pk>/", views.SupplierDetailView.as_view(), name="supplier_detail"),

    # ---- Payments ----------------------------------------------------
    path(
        "payments/",
        views.SupplierPaymentListView.as_view(),
        name="supplier_payment_list",
    ),
    path(
        "payments/add/",
        views.SupplierPaymentCreateView.as_view(),
        name="supplier_payment_add",
    ),
]