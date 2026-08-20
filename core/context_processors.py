# core/context_processors.py
from django.db.models import F


def low_stock_processor(request):
    """
    Uses request.organization, set once per request by
    core.middleware.CurrentMembershipMiddleware, instead of re-resolving
    request.user.organization (itself now a query through Membership -
    see accounts.models.User.organization) on every single page load.
    """
    org = getattr(request, "organization", None)
    if org:
        low_stock = org.products.filter(stock_quantity__lte=F("low_stock_threshold"))
        return {"low_stock_products": low_stock}
    return {"low_stock_products": []}
