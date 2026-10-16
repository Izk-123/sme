# accounts/views.py
"""
Authentication, profile, team, settings, and invitation views.

This module is the accounts app's HTTP surface. It covers six distinct
flows that all touch the User model but are otherwise unrelated:

  1. Signup + contact verification       (SignupView, VerifyEmailView,
                                          ResendVerificationEmailView,
                                          VerifyEmailRequiredView)
  2. Login / logout / password change    (BusinessLoginView,
                                          ChangePasswordView)
  3. Post-login routing                  (PostLoginRouterView,
                                          CompleteSignupView)
  4. The single "my account" page        (SettingsView, ProfileRedirectView)
  5. Team management (owner-only)        (TeamListView, InviteEmployeeView,
                                          InviteSuccessView,
                                          ToggleEmployeeActiveView)
  6. Invitation acceptance (public)      (AcceptInvitationView)

Design rules applied throughout:

  * request.organization / request.membership are populated once per
    request by core.middleware.CurrentMembershipMiddleware and must be
    read from there — never re-resolved via request.user.membership.

  * Role and organization checks come from core.permissions mixins
    (RoleRequiredMixin, SubscriptionWriteRequiredMixin), not from
    ad-hoc `if request.user.role == "owner"` checks.

  * Verification sends are always best-effort. A broken SMTP server or
    an unreachable WhatsApp API must never 500 a signup or invitation.

  * Tokens are opaque and signed, not stored as rows. They encode the
    channel that delivered them — see accounts.verification — because
    "user clicked a link we sent" is not the same statement as "user
    proved the email address". Email-delivered links flip both flags;
    WhatsApp-delivered links flip only the contact flag.

  * Both login paths — our own BusinessLoginView and django-allauth's
    Google sign-in — funnel through PostLoginRouterView, so the
    "where do I send this user?" decision lives in exactly one place.
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

from .email_normalization import normalize_email
from .forms import (
    AcceptInvitationForm,
    CompleteSignupForm,
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
    step, then dispatches the confirmation link over whichever channel
    the user picked.

    Sequencing with EmailVerificationMiddleware: this view redirects to
    /onboarding/ after login, but for a fresh account
    profile.email_verified is False, so the middleware intercepts and
    bounces the user to /verify-email/required/. That's by design.
    """

    form_class = SignupForm
    template_name = "accounts/signup.html"
    success_url = reverse_lazy("onboarding")

    def form_valid(self, form):
        try:
            user = form.save()
        except IntegrityError:
            messages.error(
                self.request,
                "That username or email was just taken. Please try again.",
            )
            return self.form_invalid(form)

        login(self.request, user)

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
    Public — the link from either channel. Handles both, but treats
    them differently:

      * An email-delivered link proves the EMAIL ADDRESS — flips both
        `email_verified` and `email_address_verified`.

      * A WhatsApp-delivered link proves only the CONTACT — flips
        `email_verified` (the "app unlocked" flag) but leaves
        `email_address_verified` alone, because WhatsApp says nothing
        about the inbox.

    Tokens issued before the channel was encoded in them carry no
    channel — treated as "proven nothing specifically", which is the
    safe default.
    """

    def get(self, request, token):
        try:
            user_id, channel = verify_token(token)
        except signing.SignatureExpired:
            messages.error(
                request,
                "That confirmation link has expired. Request a new one "
                "from Settings.",
            )
            return redirect("login")
        except signing.BadSignature:
            messages.error(request, "That confirmation link isn't valid.")
            return redirect("login")

        profile = (
            UserProfile.objects
            .filter(user_id=user_id)
            .select_related("user")
            .first()
        )
        if not profile:
            messages.error(request, "That confirmation link isn't valid.")
            return redirect("login")

        first_time = not profile.email_verified

        update_fields = []
        if not profile.email_verified:
            profile.email_verified = True
            update_fields.append("email_verified")

        # The channel decides whether the EMAIL ADDRESS itself is
        # proven. Tokens issued before the channel field existed carry
        # channel=None — not treated as email proof, since we can't
        # know which transport delivered them.
        if channel == CHANNEL_EMAIL and not profile.email_address_verified:
            profile.email_address_verified = True
            update_fields.append("email_address_verified")

        if update_fields:
            profile.save(update_fields=update_fields)

        if channel == CHANNEL_EMAIL:
            messages.success(request, "Email confirmed.")
        elif channel == CHANNEL_WHATSAPP:
            messages.success(request, "Phone confirmed.")
        else:
            messages.success(request, "Account confirmed.")

        if not request.user.is_authenticated:
            return redirect("login")

        if first_time:
            org = getattr(request, "organization", None)
            if org is not None and not org.onboarding_completed:
                return redirect("onboarding")

        return redirect("home")


class ResendVerificationEmailView(LoginRequiredMixin, View):
    """
    POST-only, from Settings → Security (and the verify gate page).

    Uses the channel the user picked at signup, stored on
    UserProfile.preferred_verification_channel, so the resend goes out
    the same way the original did.

    Supports a `?force=email` query param, used by the Settings page's
    "Verify my email" button. That button exists so a user who verified
    via WhatsApp has a path back into proving their email — required
    for Google account linking.
    """

    def post(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        settings_url = f"{reverse('settings')}#security"

        if profile.email_verified and profile.email_address_verified:
            messages.info(request, "Your account is already confirmed.")
            return redirect(settings_url)

        # The `?force=email` query param overrides the stored preference.
        force_email = request.GET.get("force") == "email"
        if force_email:
            channel = CHANNEL_EMAIL
        else:
            channel = profile.preferred_verification_channel or CHANNEL_EMAIL

        label = "email" if channel == CHANNEL_EMAIL else "WhatsApp"

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
                f"Couldn't send the {label} confirmation right now — "
                f"try again shortly.",
            )
        return redirect(settings_url)


class VerifyEmailRequiredView(LoginRequiredMixin, View):
    """
    Where EmailVerificationMiddleware sends users with unverified
    contact info. The template reads
    request.user.profile.preferred_verification_channel to pick the
    right wording.
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
        Funnel both login paths through one place. PostLoginRouterView
        decides where to send the user based on whether they have a
        Membership and whether their business has finished onboarding.
        """
        return reverse("post_login_router")


class ChangePasswordView(LoginRequiredMixin, PasswordChangeView):
    """
    Any logged-in user can change their own password here. This is also
    where employees who accepted an invitation land first if
    must_change_password is set.
    """

    form_class = StyledPasswordChangeForm
    template_name = "accounts/change_password.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        response = super().form_valid(form)
        # Clear the flag *after* the password has actually been changed.
        if self.request.user.must_change_password:
            self.request.user.must_change_password = False
            self.request.user.save(update_fields=["must_change_password"])
        messages.success(self.request, "Password changed.")
        return response


# =============================================================================
# 3. POST-LOGIN ROUTING
# =============================================================================

class PostLoginRouterView(LoginRequiredMixin, View):
    """
    Single landing point after ANY successful login.

    Routing rules, in priority order:

      1. No active Membership yet  →  /complete-signup/
      2. Membership exists, business not onboarded  →  /onboarding/
      3. Otherwise  →  /dashboard/

    Rule 2 checks `Organization.onboarding_completed`, not
    `enabled_modules` — the two are deliberately separate.
    """

    def get(self, request):
        if not request.user.memberships.filter(is_active=True).exists():
            return redirect("complete_signup")

        membership = getattr(request, "membership", None)
        if membership is None:
            membership = (
                request.user.memberships
                .filter(is_active=True)
                .select_related("organization")
                .first()
            )
        if membership and not membership.organization.onboarding_completed:
            return redirect("onboarding")

        return redirect("home")


class CompleteSignupView(LoginRequiredMixin, View):
    """
    Where a new Google user lands if they have no Membership yet.

    Only reachable when the user has no active Membership. Users who
    already have one are redirected to the normal router.
    """

    template_name = "accounts/complete_signup.html"

    def get(self, request):
        if request.user.memberships.filter(is_active=True).exists():
            return redirect("post_login_router")

        form = CompleteSignupForm(user=request.user)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        if request.user.memberships.filter(is_active=True).exists():
            return redirect("post_login_router")

        form = CompleteSignupForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        organization = form.save()

        messages.success(
            request,
            f"Welcome! {organization.name} is ready to set up.",
        )
        return redirect("onboarding")


# =============================================================================
# 4. THE SINGLE "MY ACCOUNT" PAGE
# =============================================================================

class ProfileRedirectView(LoginRequiredMixin, RedirectView):
    """
    /profile/ used to be its own page; it's folded into /settings/ now.
    Kept as a redirect so old links/bookmarks still land somewhere
    sensible.
    """

    pattern_name = "settings"
    permanent = False


class SettingsView(LoginRequiredMixin, View):
    """
    The single "my account" page: Profile, Contact, Identity, Security,
    Notifications, Preferences, and Businesses tabs. Each tab-pane holds
    its own independent <form method="post">, tagged with a hidden
    `form_name` field so post() knows which one was submitted.
    """

    template_name = "accounts/settings.html"

    FORM_TAB = {
        "profile": "profile",
        "phone": "contact",
        "identity": "identity",
        "preferences": "preferences",
        "notifications": "notifications",
    }

    def _build_forms(self, request, submitted_name=None, data=None, files=None):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        preferences, _ = UserPreference.objects.get_or_create(user=request.user)
        notification_prefs, _ = NotificationPreference.objects.get_or_create(
            user=request.user
        )

        def bound(name):
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
            "preference_form": UserPreferenceForm(
                bound("preferences"), instance=preferences
            ),
            "notification_form": NotificationPreferenceForm(
                bound("notifications"), instance=notification_prefs
            ),
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
        context = dict(forms)
        context.update({
            "memberships": request.user.memberships.select_related(
                "organization", "role"
            ),
            "phone_numbers": request.user.phone_numbers.all(),
            "identities": request.user.identity_documents.all(),
            "primary_phone": request.user.phone_numbers.filter(
                is_primary=True
            ).first(),
        })
        return render(request, self.template_name, context)


# =============================================================================
# 5. TEAM MANAGEMENT (owner-only)
# =============================================================================

class TeamMixin(LoginRequiredMixin, RoleRequiredMixin):
    """
    Shared by every team-management view: owner only, scoped to
    request.organization.
    """

    allowed_roles = ["owner"]


class TeamListView(TeamMixin, ListView):
    """
    Shows every membership in the owner's current business.
    """

    template_name = "accounts/team_list.html"
    context_object_name = "memberships"

    def get_queryset(self):
        # Deliberately NOT filtering is_active=True — inactive
        # memberships need to stay visible so they can be reactivated.
        return (
            Membership.objects
            .filter(organization=self.request.organization)
            .exclude(user=self.request.user)
            .select_related("user", "role", "user__profile")
            .order_by("user__username")
        )


class InviteEmployeeView(TeamMixin, SubscriptionWriteRequiredMixin, View):
    """
    Owner fills in name/phone/role; an Invitation is created and its
    link shown once on invite_success.html via session storage.
    """

    template_name = "accounts/invite_employee.html"

    def get(self, request):
        form = InviteEmployeeForm(organization=request.organization)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = InviteEmployeeForm(
            request.POST, organization=request.organization
        )
        if form.is_valid():
            invitation = form.save(invited_by=request.user)
            request.session["last_invite_link"] = request.build_absolute_uri(
                reverse(
                    "accept_invitation",
                    kwargs={"token": invitation.token},
                )
            )
            request.session["last_invite_name"] = invitation.full_name
            return redirect("invite_success")
        return render(request, self.template_name, {"form": form})


class InviteSuccessView(TeamMixin, View):
    """
    Shows the generated invite link exactly once, then clears it from
    the session.
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
    the owner themselves.
    """

    def post(self, request, *args, **kwargs):
        membership = get_object_or_404(
            Membership,
            pk=kwargs["pk"],
            organization=request.organization,
        )

        if membership.user_id == request.user.id:
            messages.error(request, "You can't deactivate your own account.")
            return redirect("team_list")

        will_reactivate = not membership.is_active
        if will_reactivate:
            subscription = getattr(request, "subscription", None)
            if subscription is not None and not subscription.can_write:
                messages.error(
                    request,
                    "Your subscription needs renewing before you can add "
                    "team members back. You can still deactivate existing "
                    "members.",
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
# 6. INVITATION ACCEPTANCE (public)
# =============================================================================

class AcceptInvitationView(View):
    """
    Public — no login required. This is the link an owner shares with a
    new employee. The employee picks their own username and password
    here, which creates their User + Profile + Membership.

    Verification here is intentionally email-only. The inviter chooses
    how to reach the invitee outside the app, and any email the inviter
    provided is what we verify against. If the invitation has no email,
    the user is created with no email and EmailVerificationMiddleware's
    `not user.email` guard passes them straight through.
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
        form = AcceptInvitationForm(
            initial={"username": invitation.phone_number}
        )
        return render(
            request,
            self.template_name,
            {"invitation": invitation, "form": form},
        )

    def post(self, request, token):
        form = AcceptInvitationForm(request.POST)

        # select_for_update + re-checking is_valid inside the
        # transaction closes a race where two people (or two tabs)
        # submit the same invitation link at once.
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
                with transaction.atomic():  # savepoint
                    user = User.objects.create_user(
                        username=form.cleaned_data["username"],
                        email=invitation.email,
                        password=form.cleaned_data["password1"],
                    )
                    # Keep email_normalized in sync so a later Google
                    # sign-in matches this account cleanly.
                    user.email_normalized = normalize_email(
                        invitation.email or ""
                    )
                    user.save(update_fields=["email_normalized"])

                    UserProfile.objects.create(
                        user=user, first_name=invitation.full_name
                    )
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
                form.add_error(
                    "username",
                    "That username was just taken - try another.",
                )
                return render(
                    request,
                    self.template_name,
                    {"invitation": invitation, "form": form},
                )

        if user.email and not send_verification_email(user):
            messages.warning(
                request,
                "We couldn't send a verification email right now — "
                "you can resend it from Settings.",
            )

        login(request, user)
        messages.success(request, "Welcome! Your account is ready.")
        return redirect("home")