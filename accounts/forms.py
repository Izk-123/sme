from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.db import transaction
from django.db.models import Q

from core.forms import BootstrapFormMixin
from organizations.models import Organization

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


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    """Same as Django's AuthenticationForm, just Bootstrap-styled."""


class StyledPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    """Same as Django's PasswordChangeForm, just Bootstrap-styled."""


class SignupForm(BootstrapFormMixin, UserCreationForm):
    """
    Registers a new business owner AND creates their Organization,
    UserProfile, and owning Membership in one step. Every signup gets
    its own Organization; everything the user does afterwards is scoped
    to it through their Membership (not a field on User anymore).
    """

    full_name = forms.CharField(max_length=200, label="Your name")
    business_name = forms.CharField(max_length=200, label="Business name")
    terms = forms.BooleanField(
        required=True,
        label="I agree to the terms and conditions",
        error_messages={"required": "You must agree before submitting."},
    )

    class Meta:
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        if not commit:
            return user

        user.save()
        UserProfile.objects.create(user=user, first_name=self.cleaned_data["full_name"])
        organization = Organization.objects.create(
            name=self.cleaned_data["business_name"],
            business_type="retail",  # default, set properly in the onboarding wizard
        )
        owner_role = Role.get_system("owner")
        Membership.objects.create(user=user, organization=organization, role=owner_role, is_active=True)
        return user


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    """
    Backs the "Edit Profile" tab on the profile page. Bundles fields from
    three different models behind one form: UserProfile (the ModelForm's
    own fields), plus a plain User.email field and a plain phone_number
    field that read/write the user's primary PhoneNumber - the person
    filling this in doesn't need to know their contact info is split
    across models under the hood.
    """

    email = forms.EmailField(required=False)
    phone_number = forms.CharField(max_length=20, required=False, label="Primary phone")

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
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user is not None and not self.is_bound:
            self.fields["email"].initial = user.email
            primary = user.phone_numbers.filter(is_primary=True).first()
            if primary:
                self.fields["phone_number"].initial = primary.number

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email and self.user is not None:
            if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
                raise forms.ValidationError("Another account already uses this email.")
        return email

    def clean_phone_number(self):
        number = self.cleaned_data.get("phone_number", "").strip()
        if number and self.user is not None:
            if PhoneNumber.objects.filter(number=number).exclude(user=self.user).exists():
                raise forms.ValidationError("Another account already uses this phone number.")
        return number

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=commit)
        if commit and self.user is not None:
            email = self.cleaned_data.get("email", "")
            if email != self.user.email:
                self.user.email = email
                self.user.save(update_fields=["email"])
                # A changed email hasn't been proven to belong to this
                # person yet - the old verification doesn't carry over.
                profile.email_verified = False
                profile.save(update_fields=["email_verified"])

            phone_number = self.cleaned_data.get("phone_number", "").strip()
            if phone_number:
                PhoneNumber.objects.update_or_create(
                    user=self.user,
                    is_primary=True,
                    defaults={"number": phone_number},
                )
        return profile


class PhoneNumberForm(BootstrapFormMixin, forms.ModelForm):
    """Adds one extra phone number for the Contact tab on the settings page."""

    class Meta:
        model = PhoneNumber
        fields = ["number", "type", "is_primary"]

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_number(self):
        number = self.cleaned_data.get("number", "").strip()
        if number and self.user is not None:
            if PhoneNumber.objects.filter(number=number).exclude(user=self.user).exists():
                raise forms.ValidationError("Another account already uses this phone number.")
        return number

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.user = self.user
        if commit:
            instance.save()
        return instance


class IdentityDocumentForm(BootstrapFormMixin, forms.ModelForm):
    """Adds one identity document for the Identity tab on the settings page."""

    class Meta:
        model = IdentityDocument
        fields = ["document_type", "document_number", "document_photo", "issue_date", "expiry_date"]
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


class UserPreferenceForm(BootstrapFormMixin, forms.ModelForm):
    """Personal appearance/locale preferences - the Preferences tab."""

    class Meta:
        model = UserPreference
        fields = ["theme", "language", "timezone", "compact_mode"]
        widgets = {
            "theme": forms.RadioSelect,
        }


class NotificationPreferenceForm(BootstrapFormMixin, forms.ModelForm):
    """
    Every NotificationPreference field, via Meta.fields - not a
    hand-maintained list like the earlier version's `fields = [...]`
    (which only covered 3 of the model's 9 booleans and left the rest
    permanently unreachable from the UI). Adding a field to the model
    now automatically shows up here and on the Notifications tab.
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


class InviteEmployeeForm(BootstrapFormMixin, forms.Form):
    """
    Owner fills in a name/phone/role for a new employee. This creates an
    Invitation, not an account directly - the employee sets their own
    password by following the invite link (see AcceptInvitationForm /
    AcceptInvitationView). "Owner" is deliberately excluded from the role
    choices here: minting a co-owner is a deliberate action taken in
    /admin/, not a checkbox on this form.
    """

    full_name = forms.CharField(max_length=200)
    phone_number = forms.CharField(max_length=20, required=False, help_text="Used to pre-fill their username.")
    email = forms.EmailField(required=False)
    role = forms.ModelChoiceField(queryset=Role.objects.none())

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.fields["role"].queryset = (
            Role.objects.filter(Q(organization__isnull=True) | Q(organization=organization))
            .exclude(slug="owner")
        )

    def clean(self):
        cleaned = super().clean()
        phone = cleaned.get("phone_number", "").strip()
        email = cleaned.get("email", "").strip()

        if not phone and not email:
            raise forms.ValidationError("Provide at least a phone number or an email so they can be reached.")

        if phone and PhoneNumber.objects.filter(number=phone).exists():
            self.add_error("phone_number", "This phone number is already linked to an existing account.")
        if email and User.objects.filter(email__iexact=email).exists():
            self.add_error("email", "This email is already linked to an existing account.")

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

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password1") and cleaned.get("password1") != cleaned.get("password2"):
            raise forms.ValidationError("Passwords don't match.")
        username = cleaned.get("username")
        if username and User.objects.filter(username=username).exists():
            raise forms.ValidationError("That username is taken - try another.")
        return cleaned
