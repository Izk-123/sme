"""
Fires allocate_payment() when a CustomerPayment is created.

Delete the allocations on Payment delete — but they cascade
automatically thanks to `payment=FK(on_delete=CASCADE)`, so no signal
is needed for the delete side. The customer's `update_balance()` is
called from PaymentCreateView; a Payment deleted via admin won't
recalculate the balance, which is the same as before this change —
run recompute_supplier_balances (or the customer equivalent) after
any admin-level data surgery.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Payment
from .services import allocate_payment


@receiver(post_save, sender=Payment)
def on_payment_created(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        allocate_payment(instance)
    except Exception:
        # Log but don't raise: allocation is bookkeeping for the ageing
        # report, not part of the balance calculation. A failure here
        # shouldn't roll back the payment itself.
        import logging
        logging.getLogger(__name__).exception(
            "Failed to allocate payment %s", instance.pk,
        )