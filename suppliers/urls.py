# suppliers/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.SupplierListView.as_view(), name="supplier_list"),
    path("<int:pk>/", views.SupplierDetailView.as_view(), name="supplier_detail"),
]