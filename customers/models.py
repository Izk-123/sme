# customers/models.py
from django.db import models
from django.conf import settings
from organizations.models import Organization

class Customer(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    location = models.CharField(max_length=200, blank=True)
    outstanding_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def update_balance(self):
        """
        Recalculate outstanding_balance from all unpaid sales and payments.
        For now, we'll just keep it as a sum of credit sales minus payments.
        """
        total_credit = self.sales.filter(payment_method="credit").aggregate(
            total=models.Sum('total')
        )['total'] or 0
        total_payments = self.payments.aggregate(
            total=models.Sum('amount')
        )['total'] or 0
        self.outstanding_balance = total_credit - total_payments
        self.save(update_fields=['outstanding_balance'])


class Payment(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("airtel_money", "Airtel Money"),
        ("tnm_mpamba", "TNM Mpamba"),
        ("bank", "Bank Transfer"),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="payments")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default="cash")
    reference = models.CharField(max_length=100, blank=True, help_text="Optional reference, e.g., invoice or transaction ID")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"{self.customer.name} - MK{self.amount} ({self.payment_method})"