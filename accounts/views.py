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

from core.permissions import RoleRequiredMixin

from .emails import send_verification_email, verify_token
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


class SignupView(CreateView):
    """Creates the Organization + owner User + Profile + Membership in one
    step (see SignupForm), then sends them to the onboarding wizard."""

    form_class = SignupForm
    template_name = "accounts/signup.html"
    success_url = reverse_lazy("onboarding")

    def form_valid(self, form):
        try:
            user = form.save()
        except IntegrityError:
            # Belt-and-braces: form validation already checks username/email
            # uniqueness, so this only fires on a genuine race (two signups
            # for the same username landing at once) - rare, but a raw
            # IntegrityError would otherwise 500 instead of showing a message.
            messages.error(
                self.request,
                "That username or email was just taken. Please try again.",
            )
            return self.form_invalid(form)

        login(self.request, user)
        if user.email and not send_verification_email(user):
            messages.warning(
                self.request,
                "We couldn't send a verification email right now - you can resend it from Settings.",
            )
        elif user.email:
            messages.info(self.request, "Check your email to confirm your account.")
        return redirect(self.success_url)


class VerifyEmailView(View):
    """Public - the link from the verification email. Confirms the token,
    marks the profile verified, and sends the person somewhere sensible."""

    def get(self, request, token):
        try:
            user_id = verify_token(token)
        except signing.SignatureExpired:
            messages.error(request, "That verification link has expired. Request a new one from Settings.")
            return redirect("login")
        except signing.BadSignature:
            messages.error(request, "That verification link isn't valid.")
            return redirect("login")

        profile = UserProfile.objects.filter(user_id=user_id).select_related("user").first()
        if not profile:
            messages.error(request, "That verification link isn't valid.")
            return redirect("login")

        if not profile.email_verified:
            profile.email_verified = True
            profile.save(update_fields=["email_verified"])
        messages.success(request, "Email confirmed.")

        return redirect("settings" if request.user.is_authenticated else "login")


class ResendVerificationEmailView(LoginRequiredMixin, View):
    """POST-only, from the Security tab on Settings."""

    def post(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        if profile.email_verified:
            messages.info(request, "Your email is already confirmed.")
        elif not request.user.email:
            messages.error(request, "Add an email address first.")
        elif send_verification_email(request.user):
            messages.success(request, "Verification email sent.")
        else:
            messages.error(request, "Couldn't send the email right now - try again shortly.")
        return redirect(f"{reverse('settings')}#security")


class BusinessLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm


class ChangePasswordView(LoginRequiredMixin, PasswordChangeView):
    """
    Any logged-in user can change their own password here. This is also
    where employees who accepted an invitation land first if
    must_change_password is set - see core/middleware.py's
    ForcePasswordChangeMiddleware.
    """

    form_class = StyledPasswordChangeForm
    template_name = "accounts/change_password.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.user.must_change_password:
            self.request.user.must_change_password = False
            self.request.user.save(update_fields=["must_change_password"])
        messages.success(self.request, "Password changed.")
        return response


class ProfileRedirectView(LoginRequiredMixin, RedirectView):
    """/profile/ used to be its own page; it's folded into /settings/ now
    (the Profile tab there) so there's one place that edits the user's
    own account instead of two overlapping ones. Kept as a redirect so
    old links/bookmarks still land somewhere sensible."""

    pattern_name = "settings"
    permanent = False


class SettingsView(LoginRequiredMixin, View):
    """
    The single "my account" page: Profile, Contact, Identity, Security,
    Notifications, Preferences, and Businesses tabs - see
    templates/accounts/settings.html. Each tab-pane holds its own
    independent <form method="post">, tagged with a hidden `form_name`
    field so post() knows which one was submitted; only that form is
    bound and validated; the rest stay fresh/unbound for redisplay.

    Deliberately NOT built: Devices/Sessions and My Activity tabs (no
    UserSession/AuditLog model exists to back them - see the accounts
    refactor notes) and working 2FA (the Security tab shows it as a
    clearly-disabled "coming soon" control rather than a toggle that
    doesn't actually do anything).
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
        notification_prefs, _ = NotificationPreference.objects.get_or_create(user=request.user)

        def bound(name):
            return data if submitted_name == name else None

        return {
            "profile": profile,
            "profile_form": ProfileForm(
                bound("profile"), files if submitted_name == "profile" else None,
                instance=profile, user=request.user,
            ),
            "phone_form": PhoneNumberForm(bound("phone"), user=request.user),
            "identity_form": IdentityDocumentForm(
                bound("identity"), files if submitted_name == "identity" else None,
                user=request.user,
            ),
            "preference_form": UserPreferenceForm(bound("preferences"), instance=preferences),
            "notification_form": NotificationPreferenceForm(bound("notifications"), instance=notification_prefs),
        }

    def get(self, request):
        return self._render(request, self._build_forms(request))

    def post(self, request):
        form_name = request.POST.get("form_name")
        forms = self._build_forms(request, submitted_name=form_name, data=request.POST, files=request.FILES)

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
            "memberships": request.user.memberships.select_related("organization", "role"),
            "phone_numbers": request.user.phone_numbers.all(),
            "identities": request.user.identity_documents.all(),
            "primary_phone": request.user.phone_numbers.filter(is_primary=True).first(),
        })
        return render(request, self.template_name, context)


class TeamMixin(LoginRequiredMixin, RoleRequiredMixin):
    """Shared by every team-management view: owner only, scoped to
    request.organization (the business they're currently acting as)."""

    allowed_roles = ["owner"]


class TeamListView(TeamMixin, ListView):
    """Shows every membership in the owner's current business (never
    another business, even if the owner also has a membership there)."""

    template_name = "accounts/team_list.html"
    context_object_name = "memberships"

    def get_queryset(self):
        # Deliberately NOT filtering is_active=True here - inactive
        # memberships need to stay visible so ToggleEmployeeActiveView
        # can reactivate them. Filter/badge inactive ones in the template.
        return (
            Membership.objects.filter(organization=self.request.organization)
            .exclude(user=self.request.user)
            .select_related("user", "role", "user__profile")
            .order_by("user__username")
        )


class InviteEmployeeView(TeamMixin, View):
    """Owner fills in name/phone/role; an Invitation is created and its
    link shown once on invite_success.html, via session storage (cleared
    after that one render) - same pattern the old temp-password flow used,
    just carrying a link instead of a password."""

    template_name = "accounts/invite_employee.html"

    def get(self, request):
        form = InviteEmployeeForm(organization=request.organization)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = InviteEmployeeForm(request.POST, organization=request.organization)
        if form.is_valid():
            invitation = form.save(invited_by=request.user)
            request.session["last_invite_link"] = request.build_absolute_uri(
                reverse("accept_invitation", kwargs={"token": invitation.token})
            )
            request.session["last_invite_name"] = invitation.full_name
            return redirect("invite_success")
        return render(request, self.template_name, {"form": form})


class InviteSuccessView(TeamMixin, View):
    """Shows the generated invite link exactly once, then clears it from
    the session so a page refresh can't leak it again."""

    def get(self, request):
        link = request.session.pop("last_invite_link", None)
        name = request.session.pop("last_invite_name", None)
        if not link:
            return redirect("team_list")
        return render(request, "accounts/invite_success.html", {"invite_link": link, "invite_name": name})


class AcceptInvitationView(View):
    """
    Public - no login required. This is the link an owner shares with a
    new employee (WhatsApp, SMS, in person). No email server or SMS
    gateway needed on our side; the owner does the sending however they
    normally reach the employee. The employee picks their own username
    and password here, which creates their User + Profile + Membership.
    """

    template_name = "accounts/accept_invitation.html"

    def get(self, request, token):
        invitation = get_object_or_404(Invitation, token=token)
        if not invitation.is_valid:
            return render(request, self.template_name, {"invitation": invitation, "expired": True})
        form = AcceptInvitationForm(initial={"username": invitation.phone_number})
        return render(request, self.template_name, {"invitation": invitation, "form": form})

    def post(self, request, token):
        form = AcceptInvitationForm(request.POST)

        # select_for_update + re-checking is_valid inside the transaction
        # closes a race where two people (or two tabs) submit the same
        # invitation link at once - without this, both requests could pass
        # the earlier is_valid() check before either had saved, creating
        # two accounts from one invitation.
        with transaction.atomic():
            invitation = get_object_or_404(Invitation.objects.select_for_update(), token=token)
            if not invitation.is_valid:
                return render(request, self.template_name, {"invitation": invitation, "expired": True})

            if not form.is_valid():
                return render(request, self.template_name, {"invitation": invitation, "form": form})

            try:
                with transaction.atomic():  # savepoint - see note below
                    user = User.objects.create_user(
                        username=form.cleaned_data["username"],
                        email=invitation.email,
                        password=form.cleaned_data["password1"],
                    )
                    UserProfile.objects.create(user=user, first_name=invitation.full_name)
                    if invitation.phone_number:
                        PhoneNumber.objects.create(user=user, number=invitation.phone_number, is_primary=True)
                    Membership.objects.create(
                        user=user,
                        organization=invitation.organization,
                        role=invitation.role,
                        is_active=True,
                    )
                    invitation.status = "accepted"
                    invitation.accepted_by = user
                    invitation.accepted_at = timezone.now()
                    invitation.save(update_fields=["status", "accepted_by", "accepted_at"])
            except IntegrityError:
                # Nested atomic() above = a savepoint, so this only rolls
                # back the creation attempt, not the outer select_for_update
                # transaction - without that nesting, catching the error
                # here would still leave the outer transaction broken, and
                # the render() below would 500 with TransactionManagementError
                # the moment it touched the DB again.
                form.add_error("username", "That username was just taken - try another.")
                return render(request, self.template_name, {"invitation": invitation, "form": form})

        if user.email and not send_verification_email(user):
            messages.warning(request, "We couldn't send a verification email right now - you can resend it from Settings.")

        login(request, user)
        messages.success(request, "Welcome! Your account is ready.")
        return redirect("home")


class ToggleEmployeeActiveView(TeamMixin, View):
    """Deactivates/reactivates a membership. Scoped to request.organization
    so an owner can never touch another business's members, and excludes
    the owner themselves so they can't lock themselves out."""

    def post(self, request, *args, **kwargs):
        membership = get_object_or_404(
            Membership,
            pk=kwargs["pk"],
            organization=request.organization,
        )
        if membership.user_id == request.user.id:
            messages.error(request, "You can't deactivate your own account.")
            return redirect("team_list")

        membership.is_active = not membership.is_active
        membership.save(update_fields=["is_active"])
        messages.success(
            request,
            f"{membership.user.username} is now {'active' if membership.is_active else 'inactive'}.",
        )
        return redirect("team_list")
