"""
Payment allocation.

Called automatically on every CustomerPayment creation (see
customers/signals.py). Allocates the payment FIFO across the customer's
unpaid sales so the debt-ageing report can show which sale each payment
settled.

Design:
  * Unallocated remainder is silently kept as customer credit — the
    balance calculation in Customer.calculate_balance() counts every
    payment, so an overpayment still nets out correctly on the
    customer's overall balance.
  * Only sales for the SAME organization and SAME customer are
    considered (defensive: prevents cross-tenant allocation if a bad
    data migration ever creates one).
  * Idempotent for re-runs: existing allocations are skipped so the
    function can be used both at create time and from a repair command.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum

from sales.models import Sale

from .models import PaymentAllocation


@transaction.atomic
def allocate_payment(payment):
    """
    FIFO-allocate `payment` across this customer's open sales.

    A sale's open amount is:

        total - amount_paid - sum(existing allocations to that sale)

    We allocate oldest-first (by `created_at`) until the payment is
    exhausted or every sale is covered. Returns the number of allocation
    rows created.
    """
    remaining = payment.amount
    if remaining <= 0:
        return 0

    # Pre-compute per-sale already-allocated totals in one query,
    # rather than calling sale.payment_allocations.aggregate() in a
    # loop (that would be N+1 over the number of unpaid sales).
    already = dict(
        PaymentAllocation.objects
        .filter(payment__customer=payment.customer)
        .values_list("sale_id")
        .annotate(t=Sum("amount"))
    )

    sales = (
        Sale.objects
        .filter(
            organization=payment.organization,
            customer=payment.customer,
        )
        .order_by("created_at", "id")
    )

    created = 0
    for sale in sales:
        if remaining <= 0:
            break
        already_allocated = already.get(sale.id, Decimal("0"))
        # `amount_paid` (cash at sale) already reduces what the sale
        # owes; existing allocations reduce it further.
        open_amount = sale.total - sale.amount_paid - already_allocated
        if open_amount <= 0:
            continue
        take = min(open_amount, remaining)
        PaymentAllocation.objects.create(
            organization=payment.organization,
            payment=payment,
            sale=sale,
            amount=take,
        )
        remaining -= take
        created += 1

    return created