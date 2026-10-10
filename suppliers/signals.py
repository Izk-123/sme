"""Supplier balance signals — recompute on any related change."""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from expenses.models import Expense
from sales.models import StockMovement

from .models import Supplier, SupplierPayment


def _refresh(supplier_id):
    """Recompute a supplier's balance by id — safe post-delete."""
    if not supplier_id:
        return
    supplier = Supplier.objects.filter(pk=supplier_id).first()
    if supplier:
        supplier.update_balance()


@receiver([post_save, post_delete], sender=Expense)
def on_expense_change(sender, instance, **kwargs):
    _refresh(instance.supplier_id)


@receiver([post_save, post_delete], sender=StockMovement)
def on_stock_movement_change(sender, instance, **kwargs):
    if instance.movement_type == "purchase":
        _refresh(instance.supplier_id)


@receiver([post_save, post_delete], sender=SupplierPayment)
def on_payment_change(sender, instance, **kwargs):
    _refresh(instance.supplier_id)
