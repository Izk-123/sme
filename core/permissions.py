"""
Shared role-based access control for class-based views.

Usage on any view:

    class RecordSaleView(RoleRequiredMixin, OrganizationMixin, TemplateView):
        allowed_roles = ["owner", "cashier"]
        ...

Both mixins now independently redirect unauthenticated users to login,
rather than relying on LoginRequiredMixin being listed first and every
future view remembering the correct order - a view that forgets
LoginRequiredMixin no longer silently skips these checks for anonymous
users. LoginRequiredMixin can still be included for its own sake (e.g.
its `login_url`/`redirect_field_name` customization), but isn't required
for these two to be safe.

Role and organization now come from request.membership / request.organization
(set by core.middleware.CurrentMembershipMiddleware), not from fields on
User directly - see accounts.models.Membership.
"""
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect


class RoleRequiredMixin:
    # Every role slug that should be able to reach this view. Leave empty
    # to allow any authenticated user with an active membership through.
    allowed_roles = []

    # Where to send someone who's logged in but not allowed here.
    permission_denied_redirect = "home"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        if self.allowed_roles:
            membership = getattr(request, "membership", None)
            role_slug = membership.role.slug if membership and membership.role_id else None
            if role_slug not in self.allowed_roles:
                messages.error(
                    request,
                    "Your account role doesn't have access to that page. "
                    "Ask your business owner if you think this is wrong.",
                )
                return redirect(self.permission_denied_redirect)
        return super().dispatch(request, *args, **kwargs)


class OrganizationMixin:
    """
    Exposes the current business via get_organization(). Resolution
    itself happens once per request in CurrentMembershipMiddleware; this
    mixin just enforces that a business was actually resolved before the
    view runs, and sends the user somewhere sensible if not (e.g. a
    Django superuser created via createsuperuser, who has no Membership
    by default).
    """

    def get_organization(self):
        return self.request.organization

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        if not getattr(request, "organization", None):
            messages.error(
                request,
                "Your account isn't linked to a business yet. "
                "Create a Membership for this user in /admin/, or sign up for a new business account.",
            )
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)


class SubscriptionWriteRequiredMixin:
    """
    Blocks write requests (anything but GET/HEAD/OPTIONS) when the
    organization's subscription is Restricted or Cancelled - see
    subscriptions.models.Subscription.can_write. Viewing and exporting
    existing data stays available (that's just a normal GET, which this
    mixin never touches); only *creating new records* gets stopped,
    matching the design discussion's Restricted-mode rule.

    Add this to any view that creates a business record - recording a
    sale, receiving stock, inviting an employee, adding an expense, etc.
    Editing/viewing existing records is a per-app judgment call, not
    blanket-blocked here.

    Requires subscriptions.middleware.SubscriptionMiddleware to have run
    (sets request.subscription) - list this mixin after OrganizationMixin
    so request.organization already exists, though in practice
    SubscriptionMiddleware runs at the request level regardless of MRO.
    """

    subscription_blocked_redirect = "subscription_detail"

    def dispatch(self, request, *args, **kwargs):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            subscription = getattr(request, "subscription", None)
            if subscription is not None and not subscription.can_write:
                messages.error(
                    request,
                    "Your subscription needs renewing before you can add new records. "
                    "You can still view and export your existing data.",
                )
                return redirect(self.subscription_blocked_redirect)
        return super().dispatch(request, *args, **kwargs)
