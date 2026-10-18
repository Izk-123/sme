"""
Supplier URL routing.

Order note: literal prefixes ("add/", "payments/") must come BEFORE
the <int:pk>/ catch-all, otherwise Django can't route them — the
< int:pk > pattern would match the string "add" and try to cast it.
"""
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