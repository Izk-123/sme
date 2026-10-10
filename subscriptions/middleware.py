# subscriptions/middleware.py
from .services import get_subscription


class SubscriptionMiddleware:
    """
    Sets request.subscription for the current request.organization
    (set by core.middleware.CurrentMembershipMiddleware, which this
    must run after - see MIDDLEWARE in settings.py). None if the user
    isn't authenticated or has no current organization.

    Lets views/templates do `{% if request.subscription.can_write %}`
    or `request.subscription.has_feature("barcode")` without every one
    of them calling get_subscription() themselves.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.subscription = None
        organization = getattr(request, "organization", None)
        if organization is not None:
            request.subscription = get_subscription(organization)
        return self.get_response(request)
