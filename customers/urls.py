# customers/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.CustomerListView.as_view(), name="customer_list"),
    path("<int:pk>/", views.CustomerDetailView.as_view(), name="customer_detail"),
    path("payment/add/", views.PaymentCreateView.as_view(), name="payment_add"),
]