from django.shortcuts import redirect
from django.urls import reverse


class CurrentMembershipMiddleware:
    """
    Resolves which business a logged-in user is currently acting as and
    attaches it to the request as request.membership / request.organization.
    Must run after AuthenticationMiddleware (needs request.user) and before
    anything that reads request.organization, notably
    ForcePasswordChangeMiddleware's exempt-path check doesn't need it, but
    core.permissions and core.context_processors do.

    A user can hold more than one Membership (see accounts.models.Membership -
    e.g. owner of one business, cashier at another). Until there's a
    "switch business" UI, this picks their first active membership.
    Session key 'active_membership_id' is reserved for that future switcher -
    set it and this middleware will honor it automatically.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.membership = None
        request.organization = None

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            membership = None
            membership_id = request.session.get("active_membership_id")
            if membership_id:
                membership = (
                    user.memberships.filter(pk=membership_id, is_active=True)
                    .select_related("organization", "role")
                    .first()
                )
            if membership is None:
                membership = (
                    user.memberships.filter(is_active=True).select_related("organization", "role").first()
                )
            request.membership = membership
            request.organization = membership.organization if membership else None

        return self.get_response(request)


class ForcePasswordChangeMiddleware:
    """
    If a logged-in user has must_change_password=True (set when an
    employee accepts an invitation - see accounts/models.py's Invitation
    and accounts/views.py's AcceptInvitationView), every request except a
    short allow-list gets redirected to the change-password page. This
    is what makes "temporary" actually temporary instead of a permanent
    password nobody's forced to update.
    """

    EXEMPT_PREFIXES = ("/change-password", "/logout", "/admin", "/static", "/media", "/invite")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user
            and user.is_authenticated
            and getattr(user, "must_change_password", False)
            and not any(request.path.startswith(p) for p in self.EXEMPT_PREFIXES)
        ):
            return redirect(reverse("change_password"))
        return self.get_response(request)
