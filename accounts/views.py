# accounts/views.py
"""
Authentication, profile, team, settings, and invitation views.

This module is the accounts app's HTTP surface. It covers five distinct
flows that all touch the User model but are otherwise unrelated:

  1. Signup + contact verification       (SignupView, VerifyEmailView,
                                          ResendVerificationEmailView,
                                          VerifyEmailRequiredView)
  2. Login / logout / password change    (BusinessLoginView,
                                          ChangePasswordView)
  3. The single "my account" page        (SettingsView, ProfileRedirectView)
  4. Team management (owner-only)        (TeamListView, InviteEmployeeView,
                                          InviteSuccessView,
                                          ToggleEmployeeActiveView)
  5. Invitation acceptance (public)      (AcceptInvitationView)

Design rules applied throughout:

  * request.organization / request.membership are populated once per
    request by core.middleware.CurrentMembershipMiddleware and must be
    read from there — never re-resolved via request.user.membership,
    which would issue a duplicate query per page load.

  * Role and organization checks come from core.permissions mixins
    (RoleRequiredMixin, SubscriptionWriteRequiredMixin), not from
    ad-hoc `if request.user.role == "owner"` checks — the mixins are
    already hardened against the "forgot LoginRequiredMixin" footgun.

  * Verification sends are always best-effort. A broken SMTP server or
    an unreachable WhatsApp API must never 500 a signup or invitation
    flow — see accounts.verification for the contract, and the callers
    below for how the result is surfaced to the user.

  * Tokens are opaque and signed (django.core.signing), not stored as
    rows. See accounts.verification.make_verification_token for the
    format, and _build_verification_url for how the link is constructed.
"""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core import signing
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, ListView, RedirectView

from core.permissions import RoleRequiredMixin, SubscriptionWriteRequiredMixin

from .forms import (
    AcceptInvitationForm,
    IdentityDocumentForm,
    InviteEmployeeForm,
    LoginForm,
    NotificationPreferenceForm,
    PhoneNumberForm,
    ProfileForm,
    SignupForm,
    StyledPasswordChangeForm,
    UserPreferenceForm,
)
from .models import (
    Invitation,
    Membership,
    NotificationPreference,
    PhoneNumber,
    User,
    UserPreference,
    UserProfile,
)
from .verification import (
    CHANNEL_EMAIL,
    CHANNEL_WHATSAPP,
    send_verification,
    send_verification_email,
    verify_token,
)


# =============================================================================
# 1. SIGNUP + CONTACT VERIFICATION
# =============================================================================

class SignupView(CreateView):
    """
    Creates the Organization + owner User + Profile + Membership in one
    step (see SignupForm.save), then dispatches the confirmation link
    over whichever channel the user picked on the form — email or
    WhatsApp. See accounts.verification.send_verification.

    Note on the sequencing with EmailVerificationMiddleware: this view
    redirects to /onboarding/ after login, but for a fresh account
    profile.email_verified is False, so the middleware intercepts that
    request and bounces the user to /verify-email/required/. That's by
    design — the verification gate exists precisely to hold the user
    there. Once they click the link, VerifyEmailView sends them back to
    /onboarding/, and this time the middleware lets it through because
    the profile is now verified.
    """

    form_class = SignupForm
    template_name = "accounts/signup.html"
    success_url = reverse_lazy("onboarding")

    def form_valid(self, form):
        try:
            user = form.save()
        except IntegrityError:
            # Belt-and-braces: form validation already checks username /
            # email / phone uniqueness, so this only fires on a genuine
            # race (two signups for the same identifier landing at once)
            # — rare, but a raw IntegrityError would otherwise 500
            # instead of showing a message.
            messages.error(
                self.request,
                "That username or email was just taken. Please try again.",
            )
            return self.form_invalid(form)

        login(self.request, user)

        # Dispatch on the channel the user chose. send_verification
        # returns one bool regardless of transport, so the messaging
        # below stays uniform — but we echo the channel name back to the
        # user, because "we couldn't email you" and "we couldn't WhatsApp
        # you" imply different next steps (check spam vs. check number).
        channel = form.cleaned_data["verification_channel"]
        label = "email" if channel == CHANNEL_EMAIL else "WhatsApp"

        if send_verification(user, channel):
            messages.info(
                self.request,
                f"Check your {label} to confirm your account.",
            )
        else:
            messages.warning(
                self.request,
                f"We couldn't send your {label} confirmation right now — "
                f"you can try again from Settings.",
            )

        return redirect(self.success_url)


class VerifyEmailView(View):
    """
    Public — this is the link that lands in the user's inbox (email) or
    chat (WhatsApp). Despite the class name (kept for URL stability),
    it handles both channels: the token and URL are identical whichever
    transport delivered them. That's a feature — if a user picked
    WhatsApp and their phone is acting up, the same endpoint will
    process an email resend.

    Routes the user to the right next step:

      * First-time verification + business hasn't finished onboarding
        → /onboarding/ (the wizard). This is the important case: without
          it, the signup flow's success_url=reverse_lazy("onboarding")
          gets short-circuited by the middleware and the user ends up
          on an empty dashboard instead.
      * Re-clicking an old link, or verifying into an already-configured
        business → home.
      * Link opened on a different device (no session cookie) → login.

    The key signal is `first_time`: whether email_verified was False
    *before* this call. We capture it before flipping the flag, because
    that's the only thing distinguishing "just crossed the threshold"
    from "clicked an old link" — the flag itself can't tell you.
    """

    def get(self, request, token):
        try:
            user_id = verify_token(token)
        except signing.SignatureExpired:
            messages.error(
                request,
                "That confirmation link has expired. Request a new one from Settings.",
            )
            return redirect("login")
        except signing.BadSignature:
            messages.error(request, "That confirmation link isn't valid.")
            return redirect("login")

        profile = (
            UserProfile.objects.filter(user_id=user_id)
            .select_related("user")
            .first()
        )
        if not profile:
            messages.error(request, "That confirmation link isn't valid.")
            return redirect("login")

        # Capture BEFORE flipping the flag — this is the only signal that
        # distinguishes "first time crossing the verified threshold" from
        # "user re-clicked an old link weeks later".
        first_time = not profile.email_verified
        if first_time:
            profile.email_verified = True
            profile.save(update_fields=["email_verified"])

        # Neutral wording: the user could have arrived here from either
        # transport, so don't say "Email confirmed" when they used
        # WhatsApp.
        messages.success(request, "Account confirmed.")

        # Not logged in: the link was opened on another device/browser,
        # or the session has since expired. They need to authenticate
        # first — BusinessLoginView below will pick them up and (if their
        # business still needs onboarding) send them to the wizard.
        if not request.user.is_authenticated:
            return redirect("login")

        # First-time verification on a business that hasn't finished
        # onboarding → walk them through the wizard. Re-verification
        # later, or verification into a business that's already set up,
        # goes to the dashboard as before. `org is not None` guards the
        # edge case of a superuser with no Membership at all.
        if first_time:
            org = getattr(request, "organization", None)
            if org is not None and not org.enabled_modules:
                return redirect("onboarding")

        return redirect("home")


class ResendVerificationEmailView(LoginRequiredMixin, View):
    """
    POST-only, from Settings → Security (and the verify gate page).

    Uses the channel the user picked at signup, stored on
    UserProfile.preferred_verification_channel, so the resend goes out
    the same way the original did. Switching channels is a bigger
    feature (the new contact has to be verified independently) and
    isn't offered here — the user can update their contact info on the
    Profile / Contact tabs first, and a future "switch channel" action
    would flip the stored preference and trigger a fresh send.
    """

    def post(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        settings_url = f"{reverse('settings')}#security"

        if profile.email_verified:
            messages.info(request, "Your account is already confirmed.")
            return redirect(settings_url)

        channel = profile.preferred_verification_channel or CHANNEL_EMAIL
        label = "email" if channel == CHANNEL_EMAIL else "WhatsApp"

        # Pre-flight the contact info so we can give a specific error
        # ("add an email address") rather than a generic send failure.
        # Without this, a WhatsApp-channel user with no phone on file
        # would get the vague "couldn't send" message from the
        # dispatcher's return value.
        if channel == CHANNEL_EMAIL and not request.user.email:
            messages.error(
                request,
                "Add an email address in the Contact tab first.",
            )
            return redirect(settings_url)
        if channel == CHANNEL_WHATSAPP and not request.user.phone_numbers.filter(
            is_primary=True
        ).exists():
            messages.error(
                request,
                "Add a WhatsApp number in the Contact tab first.",
            )
            return redirect(settings_url)

        if send_verification(request.user, channel):
            messages.success(request, f"Confirmation link sent by {label}.")
        else:
            messages.error(
                request,
                f"Couldn't send the {label} confirmation right now — try again shortly.",
            )
        return redirect(settings_url)


class VerifyEmailRequiredView(LoginRequiredMixin, View):
    """
    Where EmailVerificationMiddleware sends users with unverified
    contact info. Renders a "check your email / WhatsApp" page with a
    resend button; the middleware's ALLOWED_URL_NAMES set includes this
    view's URL name so that rendering it doesn't cause an infinite
    redirect loop.

    The template reads request.user.profile.preferred_verification_channel
    to pick the right wording — see accounts/verify_email_required.html.
    No channel logic lives here; the template handles the copy switch.
    """

    template_name = "accounts/verify_email_required.html"

    def get(self, request):
        return render(request, self.template_name)


# =============================================================================
# 2. LOGIN / PASSWORD CHANGE
# =============================================================================

class BusinessLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm

    def get_success_url(self):
        """
        Override LOGIN_REDIRECT_URL for the one case it gets wrong:
        a brand-new owner who verified their contact info on another
        device (so they weren't logged in when they clicked the link)
        and is now logging in for the first time. Without this override
        they'd land on an empty dashboard with enabled_modules == [].

        request.organization isn't available here — CurrentMembership-
        Middleware runs before authentication, so the login request
        itself had no user to attach an organization to. Resolve the
        membership directly.
        """
        membership = (
            self.request.user.memberships
            .filter(is_active=True)
            .select_related("organization")
            .first()
        )
        if membership and not membership.organization.enabled_modules:
            return reverse("onboarding")
        return super().get_success_url()


class ChangePasswordView(LoginRequiredMixin, PasswordChangeView):
    """
    Any logged-in user can change their own password here. This is also
    where employees who accepted an invitation land first if
    must_change_password is set — see core/middleware.py's
    ForcePasswordChangeMiddleware.
    """

    form_class = StyledPasswordChangeForm
    template_name = "accounts/change_password.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        response = super().form_valid(form)
        # Clear the flag *after* the password has actually been changed,
        # so a failed change (validation error) leaves the user still
        # required to change on the next request.
        if self.request.user.must_change_password:
            self.request.user.must_change_password = False
            self.request.user.save(update_fields=["must_change_password"])
        messages.success(self.request, "Password changed.")
        return response


# =============================================================================
# 3. THE SINGLE "MY ACCOUNT" PAGE
# =============================================================================

class ProfileRedirectView(LoginRequiredMixin, RedirectView):
    """
    /profile/ used to be its own page; it's folded into /settings/ now
    (the Profile tab there) so there's one place that edits the user's
    own account instead of two overlapping ones. Kept as a redirect so
    old links/bookmarks still land somewhere sensible.
    """

    pattern_name = "settings"
    permanent = False


class SettingsView(LoginRequiredMixin, View):
    """
    The single "my account" page: Profile, Contact, Identity, Security,
    Notifications, Preferences, and Businesses tabs — see
    templates/accounts/settings.html. Each tab-pane holds its own
    independent <form method="post">, tagged with a hidden `form_name`
    field so post() knows which one was submitted; only that form is
    bound and validated; the rest stay fresh/unbound for redisplay.

    Deliberately NOT built: Devices/Sessions and My Activity tabs (no
    UserSession/AuditLog model exists to back them) and working 2FA
    (the Security tab shows it as a clearly-disabled "coming soon"
    control rather than a toggle that doesn't actually do anything).
    """

    template_name = "accounts/settings.html"

    # Maps a submitted `form_name` to the hash fragment the browser
    # should scroll to after a successful save. Keeps the user on the
    # tab they were editing instead of snapping back to the first one.
    FORM_TAB = {
        "profile": "profile",
        "phone": "contact",
        "identity": "identity",
        "preferences": "preferences",
        "notifications": "notifications",
    }

    def _build_forms(self, request, submitted_name=None, data=None, files=None):
        """
        Build all five tab forms. Only the form whose name matches
        `submitted_name` gets bound to the incoming POST data — the
        others are left unbound so they render empty/fresh when we
        redisplay the page after a validation error on one of them.
        """
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        preferences, _ = UserPreference.objects.get_or_create(user=request.user)
        notification_prefs, _ = NotificationPreference.objects.get_or_create(user=request.user)

        def bound(name):
            """Return POST data iff this is the submitted form, else None."""
            return data if submitted_name == name else None

        return {
            "profile": profile,
            "profile_form": ProfileForm(
                bound("profile"),
                files if submitted_name == "profile" else None,
                instance=profile,
                user=request.user,
            ),
            "phone_form": PhoneNumberForm(bound("phone"), user=request.user),
            "identity_form": IdentityDocumentForm(
                bound("identity"),
                files if submitted_name == "identity" else None,
                user=request.user,
            ),
            "preference_form": UserPreferenceForm(bound("preferences"), instance=preferences),
            "notification_form": NotificationPreferenceForm(bound("notifications"), instance=notification_prefs),
        }

    def get(self, request):
        return self._render(request, self._build_forms(request))

    def post(self, request):
        form_name = request.POST.get("form_name")
        forms = self._build_forms(
            request,
            submitted_name=form_name,
            data=request.POST,
            files=request.FILES,
        )

        # Which of the five form objects in the dict is the one that
        # was actually submitted? Anything else (bogus form_name, or
        # missing) means we just redisplay.
        key = {
            "profile": "profile_form",
            "phone": "phone_form",
            "identity": "identity_form",
            "preferences": "preference_form",
            "notifications": "notification_form",
        }.get(form_name)

        if key and forms[key].is_valid():
            forms[key].save()
            messages.success(request, "Saved.")
            tab = self.FORM_TAB.get(form_name, "profile")
            return redirect(f"{reverse('settings')}#{tab}")

        return self._render(request, forms)

    def _render(self, request, forms):
        """
        Add the read-only side-lists the template needs (memberships,
        all phone numbers, all identity documents, primary phone for
        display). These are separate from the forms — the forms write,
        these display.
        """
        context = dict(forms)
        context.update({
            "memberships": request.user.memberships.select_related("organization", "role"),
            "phone_numbers": request.user.phone_numbers.all(),
            "identities": request.user.identity_documents.all(),
            "primary_phone": request.user.phone_numbers.filter(is_primary=True).first(),
        })
        return render(request, self.template_name, context)


# =============================================================================
# 4. TEAM MANAGEMENT (owner-only)
# =============================================================================

class TeamMixin(LoginRequiredMixin, RoleRequiredMixin):
    """
    Shared by every team-management view: owner only, scoped to
    request.organization (the business they're currently acting as).

    RoleRequiredMixin reads request.membership.role — see
    core.middleware.CurrentMembershipMiddleware for how that's set.
    """

    allowed_roles = ["owner"]


class TeamListView(TeamMixin, ListView):
    """
    Shows every membership in the owner's current business (never
    another business, even if the owner also has a membership there).
    """

    template_name = "accounts/team_list.html"
    context_object_name = "memberships"

    def get_queryset(self):
        # Deliberately NOT filtering is_active=True here — inactive
        # memberships need to stay visible so ToggleEmployeeActiveView
        # can reactivate them. Filter/badge inactive ones in the template.
        return (
            Membership.objects.filter(organization=self.request.organization)
            .exclude(user=self.request.user)
            .select_related("user", "role", "user__profile")
            .order_by("user__username")
        )


class InviteEmployeeView(TeamMixin, SubscriptionWriteRequiredMixin, View):
    """
    Owner fills in name/phone/role; an Invitation is created and its
    link shown once on invite_success.html, via session storage (cleared
    after that one render) — same pattern the old temp-password flow
    used, just carrying a link instead of a password.
    """

    template_name = "accounts/invite_employee.html"

    def get(self, request):
        form = InviteEmployeeForm(organization=request.organization)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = InviteEmployeeForm(request.POST, organization=request.organization)
        if form.is_valid():
            invitation = form.save(invited_by=request.user)
            # Stash the link in the session so it survives the redirect
            # to invite_success (browser URLs don't carry arbitrary data
            # between requests). Cleared by InviteSuccessView on read.
            request.session["last_invite_link"] = request.build_absolute_uri(
                reverse("accept_invitation", kwargs={"token": invitation.token})
            )
            request.session["last_invite_name"] = invitation.full_name
            return redirect("invite_success")
        return render(request, self.template_name, {"form": form})


class InviteSuccessView(TeamMixin, View):
    """
    Shows the generated invite link exactly once, then clears it from
    the session so a page refresh can't leak it again. If the session
    has already been cleared (e.g. user navigated here directly), fall
    back to the team list.
    """

    def get(self, request):
        link = request.session.pop("last_invite_link", None)
        name = request.session.pop("last_invite_name", None)
        if not link:
            return redirect("team_list")
        return render(
            request,
            "accounts/invite_success.html",
            {"invite_link": link, "invite_name": name},
        )


class ToggleEmployeeActiveView(TeamMixin, View):
    """
    Deactivates/reactivates a membership. Scoped to request.organization
    so an owner can never touch another business's members, and excludes
    the owner themselves so they can't lock themselves out.
    """

    def post(self, request, *args, **kwargs):
        membership = get_object_or_404(
            Membership,
            pk=kwargs["pk"],
            organization=request.organization,
        )

        # The pk filter above already limits us to this org, but this
        # extra check makes the "you can't lock yourself out" rule
        # explicit and survives any future change to the filter.
        if membership.user_id == request.user.id:
            messages.error(request, "You can't deactivate your own account.")
            return redirect("team_list")

        # Only guard *reactivation* on subscription state — deactivating
        # a member frees up a seat, which is always allowed, so a
        # business that's fallen into read-only shouldn't be stuck with
        # an unwanted active member.
        will_reactivate = not membership.is_active
        if will_reactivate:
            subscription = getattr(request, "subscription", None)
            if subscription is not None and not subscription.can_write:
                messages.error(
                    request,
                    "Your subscription needs renewing before you can add team "
                    "members back. You can still deactivate existing members.",
                )
                return redirect("subscription_detail")

        membership.is_active = not membership.is_active
        membership.save(update_fields=["is_active"])
        messages.success(
            request,
            f"{membership.user.username} is now "
            f"{'active' if membership.is_active else 'inactive'}.",
        )
        return redirect("team_list")


# =============================================================================
# 5. INVITATION ACCEPTANCE (public)
# =============================================================================

class AcceptInvitationView(View):
    """
    Public — no login required. This is the link an owner shares with a
    new employee (WhatsApp, SMS, in person). No email server or SMS
    gateway needed on our side; the owner does the sending however they
    normally reach the employee. The employee picks their own username
    and password here, which creates their User + Profile + Membership.

    Note on the verification send at the end: this flow is intentionally
    email-only. The inviter chooses how to reach the invitee outside the
    app, and any email the inviter provided on the invitation is what we
    verify against — offering a channel choice to the invitee would be a
    separate feature (channel picker on AcceptInvitationForm). If the
    invitation has no email, the user is created with no email and the
    EmailVerificationMiddleware's `not user.email` guard passes them
    straight through.
    """

    template_name = "accounts/accept_invitation.html"

    def get(self, request, token):
        invitation = get_object_or_404(Invitation, token=token)
        if not invitation.is_valid:
            return render(
                request,
                self.template_name,
                {"invitation": invitation, "expired": True},
            )
        # Pre-fill username with the phone number — most Malawian SMEs
        # have the employee's phone but not their preferred username,
        # and a phone-based username is easy to remember.
        form = AcceptInvitationForm(initial={"username": invitation.phone_number})
        return render(
            request,
            self.template_name,
            {"invitation": invitation, "form": form},
        )

    def post(self, request, token):
        form = AcceptInvitationForm(request.POST)

        # select_for_update + re-checking is_valid inside the transaction
        # closes a race where two people (or two tabs) submit the same
        # invitation link at once — without this, both requests could pass
        # the earlier is_valid() check before either had saved, creating
        # two accounts from one invitation.
        with transaction.atomic():
            invitation = get_object_or_404(
                Invitation.objects.select_for_update(), token=token
            )
            if not invitation.is_valid:
                return render(
                    request,
                    self.template_name,
                    {"invitation": invitation, "expired": True},
                )

            if not form.is_valid():
                return render(
                    request,
                    self.template_name,
                    {"invitation": invitation, "form": form},
                )

            try:
                with transaction.atomic():  # savepoint — see note below
                    user = User.objects.create_user(
                        username=form.cleaned_data["username"],
                        email=invitation.email,
                        password=form.cleaned_data["password1"],
                    )
                    UserProfile.objects.create(user=user, first_name=invitation.full_name)
                    if invitation.phone_number:
                        PhoneNumber.objects.create(
                            user=user,
                            number=invitation.phone_number,
                            is_primary=True,
                        )
                    Membership.objects.create(
                        user=user,
                        organization=invitation.organization,
                        role=invitation.role,
                        is_active=True,
                    )
                    invitation.status = "accepted"
                    invitation.accepted_by = user
                    invitation.accepted_at = timezone.now()
                    invitation.save(
                        update_fields=["status", "accepted_by", "accepted_at"]
                    )
            except IntegrityError:
                # Nested atomic() above = a savepoint, so this only rolls
                # back the creation attempt, not the outer select_for_update
                # transaction — without that nesting, catching the error
                # here would still leave the outer transaction broken, and
                # the render() below would 500 with TransactionManagementError
                # the moment it touched the DB again.
                form.add_error("username", "That username was just taken - try another.")
                return render(
                    request,
                    self.template_name,
                    {"invitation": invitation, "form": form},
                )

        # Best-effort, same contract as SignupView — a broken SMTP server
        # must not abort an otherwise-successful acceptance. Email-only
        # here; see the class docstring for why.
        if user.email and not send_verification_email(user):
            messages.warning(
                request,
                "We couldn't send a verification email right now — you can resend it from Settings.",
            )

        login(request, user)
        messages.success(request, "Welcome! Your account is ready.")
        return redirect("home")