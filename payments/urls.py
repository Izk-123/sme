from django.urls import path

from . import views

urlpatterns = [
    path("checkout/", views.InitiateSubscriptionCheckoutView.as_view(), name="initiate_subscription_checkout"),
    path("callback/", views.PaymentCallbackView.as_view(), name="payment_callback"),
    path("return/", views.PaymentReturnView.as_view(), name="payment_return"),
    path("webhooks/paychangu/", views.PayChanguWebhookView.as_view(), name="paychangu_webhook"),
]
