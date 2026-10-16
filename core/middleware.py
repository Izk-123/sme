"""
core/middleware.py

Request-scoped middleware for SME Business OS (ChumaFlow).

Declared in settings.MIDDLEWARE in this order — ordering matters:

    AuthenticationMiddleware                        (Django)
    core.middleware.CurrentMembershipMiddleware    # this file
    subscriptions.middleware.SubscriptionMiddleware
    core.middleware.ForcePasswordChangeMiddleware  # this file
    core.middleware.EmailVerificationMiddleware    # this file
    MessageMiddleware                               (Django)

Rules applied throughout this file:

  * Never touch request.user until AuthenticationMiddleware has run.
  * Never block a URL the user needs in order to unblock *themselves*
    (login, logout, the verification link, the change-password page).
  * Prefer redirecting to a safe, always-reachable page over 403 —
    the goal is to route the person to the right next step, not punish
    them.
  * Anything that needs to know "which URL is this?" must resolve it
    manually via django.urls.resolve(). request.resolver_match is NOT
    populated during the middleware request phase — Django fills it in
    after URL resolution, which happens *after* middleware runs.
    Reaching for it here caused an infinite redirect loop in the
    original EmailVerificationMiddleware.
"""

from django.conf import settings
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse


# =============================================================================
# Shared helpers
# =============================================================================

def _resolved_url_name(request):
    """
    Return the URL name for the current request, or None if the path
    doesn't match anything (i.e. would 404) or is served outside the
    URLconf (static/media under DEBUG).

    request.resolver_match is unusable here — see the module docstring.
    """
    try:
        return resolve(request.path_info).url_name
    except Resolver404:
        return None


def _is_static_or_media(path):
    """
    True for /static/... and /media/.... Never gate those — a redirect
    on a CSS/JS request just produces a page with no styling, which is
    an especially confusing failure mode when the page you're trying to
    redirect *to* is a form the user has to interact with.
    """
    for prefix in (getattr(settings, "STATIC_URL", None),
                   getattr(settings, "MEDIA_URL", None)):
        if prefix and path.startswith(prefix):
            return True
    return False


# =============================================================================
# 1. CurrentMembershipMiddleware
# =============================================================================

class CurrentMembershipMiddleware:
    """
    Resolves which business a logged-in user is currently acting as and
    attaches it to the request as request.membership / request.organization.

    Must run after AuthenticationMiddleware (needs request.user) and before
    anything that reads request.organization — notably core.permissions and
    core.context_processors.

    A user can hold more than one Membership (see accounts.models.Membership —
    e.g. owner of one business, cashier at another). Until there's a
    "switch business" UI, this picks their first active membership. The
    session key 'active_membership_id' is reserved for that future switcher:
    set it, and this middleware honors it automatically on the next request.
    """

    SESSION_KEY = "active_membership_id"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Default to None so downstream code never has to guard with
        # getattr(request, "organization", None).
        request.membership = None
        request.organization = None

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            membership = None

            # 1. Session choice, if it still points at a live membership.
            membership_id = request.session.get(self.SESSION_KEY)
            if membership_id:
                membership = (
                    user.memberships
                    .filter(pk=membership_id, is_active=True)
                    .select_related("organization", "role")
                    .first()
                )
                if membership is None:
                    # Stale pointer (they left / were deactivated from
                    # that org) — clear it so we don't keep re-checking.
                    request.session.pop(self.SESSION_KEY, None)

            # 2. Fallback: their first active membership, and remember it
            #    so subsequent requests skip step 2.
            if membership is None:
                membership = (
                    user.memberships
                    .filter(is_active=True)
                    .select_related("organization", "role")
                    .first()
                )
                if membership is not None:
                    request.session[self.SESSION_KEY] = membership.pk

            request.membership = membership
            request.organization = membership.organization if membership else None

        return self.get_response(request)


# =============================================================================
# 2. ForcePasswordChangeMiddleware
# =============================================================================

class ForcePasswordChangeMiddleware:
    """
    If a logged-in user has must_change_password=True (set when an
    employee accepts an invitation — see accounts/models.py's Invitation
    and accounts/views.py's AcceptInvitationView), every request except a
    short allow-list gets redirected to the change-password page. This
    is what makes "temporary" actually temporary instead of a permanent
    password nobody's forced to update.

    Path-prefix based (rather than URL-name based) because the exact
    allowlist here is about *infrastructure* — auth endpoints, admin,
    static assets, the invitation-acceptance flow — and those paths are
    stable. Anything the user genuinely needs in order to unblock
    themselves is listed below.

    Note on '/verify-email': this middleware runs *before*
    EmailVerificationMiddleware. Without this exemption, a user who had
    BOTH flags set (must_change_password=True AND email_verified=False)
    would be redirected to /change-password even if they clicked the
    verification link — because ForcePasswordChange would intercept the
    request first. Letting /verify-email through means the two gates
    compose: password first, then email, or either order the user
    actually reaches them.
    """

    EXEMPT_PREFIXES = (
        "/change-password",
        "/logout",
        "/admin",       # so staff can still log out / administer
        "/static",
        "/media",
        "/invite",       # accept_invitation flow (public)
        "/verify-email", # see the docstring note above
    )

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


# =============================================================================
# 3. EmailVerificationMiddleware
# =============================================================================

class EmailVerificationMiddleware:
    """
    Holds an authenticated user on the "confirm your email" page until
    they click the link in their verification email.

    Skipped for:
      * unauthenticated requests (nothing to gate),
      * staff users (so /admin/ stays reachable and a manually-created
        staffer isn't locked out),
      * accounts with no email on file (invitation acceptance permits
        phone-only accounts — there is nothing to verify).

    Skipped URLs (by name, since /verify-email/<token>/ has a variable
    path segment — a prefix check wouldn't work cleanly):
      * login / logout,
      * verify_email (the link itself),
      * verify_email_required (the gate page — MUST be in the list,
        otherwise the middleware redirects that page to itself and you
        get ERR_TOO_MANY_REDIRECTS),
      * resend_verification_email,
      * change_password (so a user with both must_change_password and an
        unverified email deals with the password first).

    Fixes the original bug: the previous version read
    request.resolver_match.url_name, which is None during the middleware
    request phase (Django only sets it after URL resolution). That made
    every request look like "not in ALLOWED_URL_NAMES", so every request
    — including /verify-email/required/ itself — was redirected to
    /verify-email/required/. _resolved_url_name() above resolves the
    path manually to get the correct answer.
    """

    ALLOWED_URL_NAMES = {
        "login",
        "logout",
        "verify_email",               # the link from the email
        "verify_email_required",      # the gate page itself
        "resend_verification_email",  # POST from the gate page
        "change_password",            # so ForcePasswordChange still works
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return self.get_response(request)
        if user.is_staff or not user.email:
            return self.get_response(request)

        # OneToOne auto-created by accounts.signals on signup, but a
        # safe lookup in case an account predates that signal.
        profile = getattr(user, "profile", None)
        if profile is None or profile.email_verified:
            return self.get_response(request)

        if _is_static_or_media(request.path_info):
            return self.get_response(request)

        if _resolved_url_name(request) in self.ALLOWED_URL_NAMES:
            return self.get_response(request)

        return redirect("verify_email_required")