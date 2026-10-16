"""
Currency formatting for templates.

Store money as Decimal in the DB (correctness); show whole kwacha in the
UI (usability). This filter takes a Decimal/float/int/None and returns
a human-formatted string like "MK21,957".

Currency symbol comes from request.organization.currency (set by
CurrentMembershipMiddleware) and falls back to "MK" if unavailable.
"""
from decimal import Decimal, InvalidOperation

from django import template
from django.template.defaultfilters import floatformat

register = template.Library()

DEFAULT_SYMBOL = "MK"


def _symbol(context):
    request = context.get("request")
    if request is None:
        return DEFAULT_SYMBOL
    org = getattr(request, "organization", None)
    if org is not None and getattr(org, "currency", None):
        return org.currency
    return DEFAULT_SYMBOL


def _to_decimal(value):
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


@register.simple_tag(takes_context=True)
def money(context, value, show_cents=False):
    """
    Format a monetary value for display.

    Usage:
        {% money sale.total %}              -> MK21,957
        {% money sale.total show_cents=True %}  -> MK21,957.46
        {% money expense.amount %}          -> MK5,000

    - Whole kwacha by default (no decimals). Pass show_cents=True only
      for contexts where cents genuinely matter (e.g. a formal invoice
      PDF for a foreign customer).
    - Thousands separator via Python's comma formatting.
    - None/empty/garbage -> MK0 (never crashes a template).
    """
    amount = _to_decimal(value)

    if show_cents:
        # Two decimal places with thousands separator
        formatted = f"{amount:,.2f}"
    else:
        # Round half-up to nearest whole kwacha, then format with commas
        rounded = amount.quantize(Decimal("1"))
        formatted = f"{rounded:,}"

    symbol = _symbol(context)
    # Negative amounts: "-MK21,957" reads cleaner than "MK-21,957"
    if formatted.startswith("-"):
        return f"-{symbol}{formatted[1:]}"
    return f"{symbol}{formatted}"