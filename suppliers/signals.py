"""
Balance signals.

Two invariants:

  1. When a related row (Expense / purchase StockMovement /
     SupplierPayment) is created, edited, or deleted, EVERY supplier
     whose balance was affected is recomputed — both the new supplier
     and, on an edit that changed the FK, the old one.

  2. A failure inside update_balance() is logged, never raised. Django
     runs post_save inside the same transaction as the triggering
     write; letting the recompute crash would roll back the
     Expense/Payment that triggered it, and the user would see
     "couldn't record" for a problem that has nothing to do with their
     action. The balance is self-healing, so a missed refresh is
     recoverable — a rolled-back payment is not.

pre_save capture exists because post_save alone can't tell whether the
FK changed. An Expense moved from supplier A to supplier B needs A's
balance refreshed too (its old debt is gone) — the `_old_supplier_id`
attribute we stash on the instance in pre_save gives post_save /
post_delete the id to refresh.
"""
import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from expenses.models import Expense
from sales.models import StockMovement

from .models import Supplier, SupplierPayment

logger = logging.getLogger(__name__)


def _refresh(supplier_id):
    """Recompute one supplier's balance. Never raises."""
    if not supplier_id:
        return
    try:
        supplier = Supplier.objects.filter(pk=supplier_id).first()
        if supplier is not None:
            supplier.update_balance()
    except Exception:
        logger.exception("Failed to refresh balance for supplier %s", supplier_id)


# ---------------------------------------------------------------------------
# pre_save: capture the state BEFORE the write.
#
# StockMovement captures movement_type too: a row edited from
# 'purchase' to 'sale' must stop counting toward the balance, so the
# (old) supplier needs a refresh even though the current row no longer
# qualifies.
# ---------------------------------------------------------------------------

@receiver(pre_save, sender=Expense)
def _capture_old_expense_supplier(sender, instance, **kwargs):
    if not instance.pk:
        return
    instance._old_supplier_id = (
        sender.objects.filter(pk=instance.pk)
        .values_list("supplier_id", flat=True)
        .first()
    )


@receiver(pre_save, sender=SupplierPayment)
def _capture_old_payment_supplier(sender, instance, **kwargs):
    if not instance.pk:
        return
    instance._old_supplier_id = (
        sender.objects.filter(pk=instance.pk)
        .values_list("supplier_id", flat=True)
        .first()
    )


@receiver(pre_save, sender=StockMovement)
def _capture_old_movement_supplier(sender, instance, **kwargs):
    if not instance.pk:
        return
    row = (
        sender.objects.filter(pk=instance.pk)
        .values_list("supplier_id", "movement_type")
        .first()
    )
    if row:
        instance._old_supplier_id, instance._old_movement_type = row


# ---------------------------------------------------------------------------
# post_save / post_delete: recompute every affected supplier.
# ---------------------------------------------------------------------------

@receiver([post_save, post_delete], sender=Expense)
def on_expense_change(sender, instance, **kwargs):
    _refresh(instance.supplier_id)
    _refresh(getattr(instance, "_old_supplier_id", None))


@receiver([post_save, post_delete], sender=SupplierPayment)
def on_payment_change(sender, instance, **kwargs):
    _refresh(instance.supplier_id)
    _refresh(getattr(instance, "_old_supplier_id", None))


@receiver([post_save, post_delete], sender=StockMovement)
def on_stock_movement_change(sender, instance, **kwargs):
    old_type = getattr(instance, "_old_movement_type", None)

    # Cheap early-out: plain sales (the high-volume case) never touch
    # a supplier balance. Only purchases (current or former) do.
    if instance.movement_type != "purchase" and old_type != "purchase":
        return

    _refresh(instance.supplier_id)
    _refresh(getattr(instance, "_old_supplier_id", None))