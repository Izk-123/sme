"""
Authentication, profile, and team-membership forms for the accounts app.

Two rules run through this module:

  * Every user-facing failure must say which field caused it and what to
    do next. Django's stock messages ("enter a correct username and
    password", "the two password fields didn't match") are technically
    accurate and practically useless — they make the user guess.
  * Uniqueness checks are case-insensitive AND normalized. "Alice" and
    "alice" must not both be registerable; "A@x.com" and "a@x.com" are
    the same account; and Gmail dot/plus variants resolve to one.
"""

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    UserCreationForm,
)
from django.db import transaction
from django.db.models import Q

from core.forms import BootstrapFormMixin
from organizations.models import Organization

from .email_normalization import normalize_email
from .models import (
    IdentityDocument,
    Invitation,
    Membership,
    NotificationPreference,
    PhoneNumber,
    Role,
    User,
    UserPreference,
    UserProfile,
)
from .verification import normalize_malawi_phone


# =============================================================================
# AUTHENTICATION
# =============================================================================

class LoginForm(BootstrapFormMixin, AuthenticationForm):
    """
    Django's AuthenticationForm with two behavioural changes:

      1. Specific failure messages. Stock Django collapses "no such
         username", "wrong password", and "account disabled" into one
         generic line, forcing the user to guess which one they hit.
         clean() below separates them.

      2. Case-insensitive username lookup. Django's default is exact —
         typing "Owner" instead of "owner" reports "invalid credentials"
         even though the account plainly exists.

    Trade-off worth naming: distinguishing "no such username" from
    "wrong password" leaks whether an account exists (user enumeration).
    For ChumaFlow that's acceptable — usernames are chosen by owners for
    a handful of staff, not guessable handles on a public service — and
    the usability win is large. If public signup ever makes usernames
    guessable, collapse the first branch back into the generic message.
    """

    error_messages = {
        **AuthenticationForm.error_messages,
        "inactive": (
            "This account has been deactivated. "
            "Ask your business owner to reactivate it."
        ),
    }

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username and password:
            if not User.objects.filter(username__iexact=username).exists():
                raise forms.ValidationError(
                    "No account found with that username. "
                    "Check the spelling, or create a new account.",
                    code="invalid_login",
                )

            self.user_cache = authenticate(
                self.request, username=username, password=password
            )
            if self.user_cache is None:
                raise forms.ValidationError(
                    "That password is incorrect. Try again, or ask your "
                    "owner to reset it.",
                    code="invalid_login",
                )

            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class StyledPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    """Same as Django's PasswordChangeForm, just Bootstrap-styled."""


# =============================================================================
# WIDGETS
# =============================================================================

class ProfilePhotoWidget(forms.ClearableFileInput):
    """
    Modern drag-and-drop image upload widget.

    Replaces the browser's stock file input with a circular dropzone
    that previews the current photo, accepts dropped files, keeps the
    native <input type="file"> in the DOM (visually hidden but
    clickable via its label), and offers a remove affordance.

    All interactivity lives in static/js/app.js under the "cf-photo-drop"
    namespace — the widget only emits markup.
    """

    template_name = "accounts/widgets/profile_photo_drop.html"

    initial_text = ""
    input_text = ""
    clear_checkbox_label = "Remove photo"

    def __init__(self, attrs=None):
        defaults = {
            "accept": "image/*",
            "class": "cf-photo-drop__input",
        }
        if attrs:
            defaults.update(attrs)
        super().__init__(defaults)


# =============================================================================
# SIGNUP
# =============================================================================

class SignupForm(BootstrapFormMixin, UserCreationForm):
    """
    Registers a new business owner AND creates their Organization,
    UserProfile, and owning Membership in one step.

    The user picks a verification channel — email or WhatsApp — and the
    chosen channel decides which contact field is required. The choice
    is stored on UserProfile.preferred_verification_channel so a later
    Resend doesn't have to guess.

    `email` is declared explicitly (required=False) so clean() can
    enforce "required iff the email radio is picked" with one clear
    error. Leaving it in Meta.fields as well would raise FieldError.
    """

    first_name = forms.CharField(max_length=150, label="First name")
    middle_name = forms.CharField(
        max_length=150,
        required=False,
        label="Middle name",
    )
    last_name = forms.CharField(max_length=150, label="Last name")
    full_name = forms.CharField(
        max_length=150,
        required=False,
        label="Full name",
        help_text=(
            "How you'd like to appear across ChumaFlow — for example "
            "'Dr. John Smith' or 'Johnny'. Leave blank to use your "
            "first and last name."
        ),
    )

    business_name = forms.CharField(max_length=200, label="Business name")

    verification_channel = forms.ChoiceField(
        choices=[("email", "Email"), ("whatsapp", "WhatsApp")],
        initial="email",
        widget=forms.RadioSelect,
        label="How should we send your confirmation link?",
    )

    email = forms.EmailField(required=False)

    phone_number = forms.CharField(
        max_length=20,
        required=False,
        label="WhatsApp number",
        help_text="e.g. 088 123 4567",
    )

    terms = forms.BooleanField(
        required=True,
        label="I agree to the terms and conditions",
        error_messages={"required": "You must agree before submitting."},
    )

    error_messages = {
        **UserCreationForm.error_messages,
        "password_mismatch": "Those passwords don't match — check both fields.",
    }

    class Meta:
        model = User
        fields = ("username",)

    # ------------------------------------------------------------------
    # Field-level cleaners
    # ------------------------------------------------------------------

    def clean_first_name(self):
        value = self.cleaned_data.get("first_name", "").strip()
        if not value:
            raise forms.ValidationError("Enter your first name.")
        return value

    def clean_last_name(self):
        value = self.cleaned_data.get("last_name", "").strip()
        if not value:
            raise forms.ValidationError("Enter your last name.")
        return value

    def clean_full_name(self):
        return self.cleaned_data.get("full_name", "").strip()

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            raise forms.ValidationError("Choose a username.")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                f"'{username}' is already taken — try a different one."
            )
        return username

    def clean_email(self):
        """
        Reject an email that is already PROVEN by another account.

        An email that is merely CLAIMED (signed up with, never verified)
        does NOT block a new signup — otherwise an attacker who guesses
        a victim's address could permanently lock the real owner out of
        registering by typing it into the form without verifying.

        When both a claim and a real signup exist, whichever side
        actually proves the email wins — and only the proven side is
        eligible for Google linking. See
        accounts.adapters.ChumaFlowSocialAdapter for the linking rule.
        """
        email = self.cleaned_data.get("email", "").strip()
        if not email:
            return email

        normalized = normalize_email(email)

        # Match on both normalized AND raw (case-insensitive). The
        # normalized form is authoritative, but rows created before the
        # 0011 migration may not have it populated yet — the fallback
        # covers that transition window.
        already_proven = User.objects.filter(
            profile__email_address_verified=True,
        ).filter(
            Q(email_normalized=normalized) | Q(email__iexact=email)
        ).exists()

        if already_proven:
            raise forms.ValidationError(
                "This email address is already in use on a verified "
                "account. Sign in instead, or contact support on WhatsApp "
                "if this is your address and you can't access the other "
                "account."
            )

        return email

    def clean_phone_number(self):
        raw = self.cleaned_data.get("phone_number", "").strip()
        if not raw:
            return ""

        normalized = normalize_malawi_phone(raw)
        if normalized is None:
            raise forms.ValidationError(
                "That doesn't look like a Malawi mobile number — "
                "try a format like 088 123 4567."
            )

        variants = [raw, normalized, f"+{normalized}", f"0{normalized[3:]}"]
        if PhoneNumber.objects.filter(number__in=variants).exists():
            raise forms.ValidationError(
                "This phone number is already linked to an account. "
                "Use a different number, or sign in with the existing one."
            )

        return normalized

    # ------------------------------------------------------------------
    # Cross-field validation
    # ------------------------------------------------------------------

    def clean(self):
        cleaned = super().clean()
        channel = cleaned.get("verification_channel")
        email = cleaned.get("email")
        phone = cleaned.get("phone_number")

        if channel == "email" and not email:
            self.add_error(
                "email",
                "Enter your email address, or choose WhatsApp instead.",
            )
        elif channel == "whatsapp" and not phone:
            self.add_error(
                "phone_number",
                "Enter your WhatsApp number, or choose email instead.",
            )

        return cleaned

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get("email", "")
        # Keep the canonical form in sync so future Google sign-ins
        # match this account even when the spelling differs (Gmail
        # dots, +tags, case).
        user.email_normalized = normalize_email(user.email)
        if not commit:
            return user

        user.save()

        UserProfile.objects.create(
            user=user,
            first_name=self.cleaned_data["first_name"],
            middle_name=self.cleaned_data["middle_name"],
            last_name=self.cleaned_data["last_name"],
            preferred_name=self.cleaned_data["full_name"],
            preferred_verification_channel=self.cleaned_data["verification_channel"],
        )

        if self.cleaned_data.get("phone_number"):
            PhoneNumber.objects.create(
                user=user,
                number=self.cleaned_data["phone_number"],
                is_primary=True,
            )

        organization = Organization.objects.create(
            name=self.cleaned_data["business_name"],
            business_type="retail",
        )
        Membership.objects.create(
            user=user,
            organization=organization,
            role=Role.get_system("owner"),
            is_active=True,
        )
        return user


class CompleteSignupForm(BootstrapFormMixin, forms.Form):
    """
    Second half of the signup flow for users who arrived via Google.

    Google handed us their name and a verified email; this form collects
    the one thing Google can't know — their business name — and creates
    the Organization + Membership.

    The first/last name fields are only *required* when the profile is
    missing them. Otherwise they're hidden in the template so the user
    sees a one-field form.
    """

    business_name = forms.CharField(
        max_length=200,
        label="Business name",
    )
    first_name = forms.CharField(max_length=150, required=False, label="First name")
    last_name = forms.CharField(max_length=150, required=False, label="Last name")

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

        if user and hasattr(user, "profile"):
            profile = user.profile
            if not profile.first_name:
                self.fields["first_name"].required = True
                self.fields["first_name"].initial = user.first_name or ""
            if not profile.last_name:
                self.fields["last_name"].required = True
                self.fields["last_name"].initial = user.last_name or ""

    def clean_business_name(self):
        name = self.cleaned_data.get("business_name", "").strip()
        if not name:
            raise forms.ValidationError("Enter your business name.")
        return name

    @transaction.atomic
    def save(self):
        profile = self.user.profile
        changed = []
        if self.cleaned_data.get("first_name") and not profile.first_name:
            profile.first_name = self.cleaned_data["first_name"]
            changed.append("first_name")
        if self.cleaned_data.get("last_name") and not profile.last_name:
            profile.last_name = self.cleaned_data["last_name"]
            changed.append("last_name")
        if changed:
            profile.save(update_fields=changed)

        organization = Organization.objects.create(
            name=self.cleaned_data["business_name"],
            business_type="retail",
        )
        Membership.objects.create(
            user=self.user,
            organization=organization,
            role=Role.get_system("owner"),
            is_active=True,
        )
        return organization


# =============================================================================
# PROFILE & CONTACT
# =============================================================================

class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    """
    Backs the "Edit Profile" tab on the settings page. Bundles fields
    from three different models behind one form: UserProfile, plus a
    plain User.email field and a plain phone_number field that read/write
    the user's primary PhoneNumber.
    """

    MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB

    email = forms.EmailField(required=False)
    phone_number = forms.CharField(
        max_length=20, required=False, label="Primary phone"
    )

    class Meta:
        model = UserProfile
        fields = [
            "first_name",
            "middle_name",
            "last_name",
            "preferred_name",
            "date_of_birth",
            "gender",
            "profile_photo",
            "address",
            "city",
            "district",
            "country",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "profile_photo": ProfilePhotoWidget(),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user is not None and not self.is_bound:
            self.fields["email"].initial = user.email
            primary = user.phone_numbers.filter(is_primary=True).first()
            if primary:
                self.fields["phone_number"].initial = primary.number

    def clean_profile_photo(self):
        photo = self.cleaned_data.get("profile_photo")
        if not photo:
            return photo

        if hasattr(photo, "size") and photo.size > self.MAX_PHOTO_BYTES:
            mb = self.MAX_PHOTO_BYTES / (1024 * 1024)
            raise forms.ValidationError(
                f"That image is too large — keep it under {mb:.0f} MB."
            )

        content_type = getattr(photo, "content_type", "") or ""
        if content_type and not content_type.startswith("image/"):
            raise forms.ValidationError(
                "Only image files (JPG, PNG, GIF, WebP) can be used as a "
                "profile photo."
            )

        return photo

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email and self.user is not None:
            if User.objects.filter(email__iexact=email).exclude(
                pk=self.user.pk
            ).exists():
                raise forms.ValidationError(
                    "Another account already uses this email."
                )
        return email

    def clean_phone_number(self):
        number = self.cleaned_data.get("phone_number", "").strip()
        if number and self.user is not None:
            if PhoneNumber.objects.filter(number=number).exclude(
                user=self.user
            ).exists():
                raise forms.ValidationError(
                    "Another account already uses this phone number."
                )
        return number

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=commit)
        if commit and self.user is not None:
            email = self.cleaned_data.get("email", "")
            if email != self.user.email:
                self.user.email = email
                # Canonical form follows the raw email everywhere.
                self.user.email_normalized = normalize_email(email)
                self.user.save(update_fields=["email", "email_normalized"])
                # Changing the address invalidates BOTH proofs. The old
                # email was verified; the new one hasn't been. If only
                # `email_verified` were reset, a user could set their
                # email to someone else's address and inherit that
                # person's Google-linking rights. Reset both.
                profile.email_verified = False
                profile.email_address_verified = False
                profile.save(update_fields=[
                    "email_verified",
                    "email_address_verified",
                ])

            phone_number = self.cleaned_data.get("phone_number", "").strip()
            if phone_number:
                PhoneNumber.objects.update_or_create(
                    user=self.user,
                    is_primary=True,
                    defaults={"number": phone_number},
                )
        return profile


class PhoneNumberForm(BootstrapFormMixin, forms.ModelForm):
    """Adds one extra phone number for the Contact tab."""

    class Meta:
        model = PhoneNumber
        fields = ["number", "type", "is_primary"]

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_number(self):
        number = self.cleaned_data.get("number", "").strip()
        if number and self.user is not None:
            if PhoneNumber.objects.filter(number=number).exclude(
                user=self.user
            ).exists():
                raise forms.ValidationError(
                    "Another account already uses this phone number."
                )
        return number

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.user = self.user
        if commit:
            instance.save()
        return instance


class IdentityDocumentForm(BootstrapFormMixin, forms.ModelForm):
    """Adds one identity document for the Identity tab."""

    class Meta:
        model = IdentityDocument
        fields = [
            "document_type",
            "document_number",
            "document_photo",
            "issue_date",
            "expiry_date",
        ]
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.user = self.user
        if commit:
            instance.save()
        return instance


# =============================================================================
# PREFERENCES
# =============================================================================

class UserPreferenceForm(BootstrapFormMixin, forms.ModelForm):
    """Personal appearance/locale preferences — the Preferences tab."""

    class Meta:
        model = UserPreference
        fields = ["theme", "language", "timezone", "compact_mode"]
        widgets = {
            "theme": forms.RadioSelect,
        }


class NotificationPreferenceForm(BootstrapFormMixin, forms.ModelForm):
    """
    Every NotificationPreference field, via Meta.fields — not a
    hand-maintained list.
    """

    class Meta:
        model = NotificationPreference
        fields = [
            "daily_sales_summary",
            "low_stock_alert",
            "out_of_stock_alert",
            "payment_overdue",
            "customer_payment_received",
            "new_login_alert",
            "password_changed_alert",
            "push_notifications",
            "email_notifications",
        ]


# =============================================================================
# TEAM & INVITATIONS
# =============================================================================

class InviteEmployeeForm(BootstrapFormMixin, forms.Form):
    """
    Owner fills in a name/phone/role for a new employee. Creates an
    Invitation, not an account directly. "Owner" is deliberately
    excluded from the role choices.
    """

    full_name = forms.CharField(max_length=200)
    phone_number = forms.CharField(
        max_length=20, required=False, help_text="Used to pre-fill their username."
    )
    email = forms.EmailField(required=False)
    role = forms.ModelChoiceField(queryset=Role.objects.none())

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.fields["role"].queryset = (
            Role.objects
            .filter(Q(organization__isnull=True) | Q(organization=organization))
            .exclude(slug="owner")
        )

    def clean(self):
        cleaned = super().clean()
        phone = cleaned.get("phone_number", "").strip()
        email = cleaned.get("email", "").strip()

        if not phone and not email:
            raise forms.ValidationError(
                "Provide at least a phone number or an email so they can "
                "be reached."
            )

        if phone and PhoneNumber.objects.filter(number=phone).exists():
            self.add_error(
                "phone_number",
                "This phone number is already linked to an existing account.",
            )
        if email and User.objects.filter(email__iexact=email).exists():
            self.add_error(
                "email",
                "This email is already linked to an existing account.",
            )

        return cleaned

    def save(self, invited_by):
        return Invitation.objects.create(
            organization=self.organization,
            role=self.cleaned_data["role"],
            invited_by=invited_by,
            full_name=self.cleaned_data["full_name"],
            phone_number=self.cleaned_data["phone_number"],
            email=self.cleaned_data["email"],
        )


class AcceptInvitationForm(BootstrapFormMixin, forms.Form):
    """The employee-facing half of the invite flow: pick a username and password."""

    username = forms.CharField(max_length=150)
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    error_messages = {
        "password_mismatch": "Those passwords don't match — check both fields.",
    }

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            raise forms.ValidationError("Choose a username.")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                f"'{username}' is already taken — try a different one."
            )
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError(
                self.error_messages["password_mismatch"],
                code="password_mismatch",
            )
        return cleaned