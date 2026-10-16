# accounts/adapters.py
"""
django-allauth adapters for ChumaFlow.

The interesting one is ChumaFlowSocialAdapter, which enforces the
careful-linking rule:

    A Google identity may be attached to an existing ChumaFlow account
    ONLY when that account's EMAIL ADDRESS has itself been proven —
    i.e. the account owner clicked a link we delivered by email.

    Verifying a phone number over WhatsApp does NOT count. WhatsApp
    proves the phone; it says nothing about the inbox. An attacker who
    can receive WhatsApp messages on a phone number is not thereby
    entitled to control the email account that owns a ChumaFlow login.

Decision tree, in order:

  * Google identity already linked  →  log in normally.

  * Google returned no email         →  treat as fresh signup.
  * Google email not verified by
    Google itself                    →  treat as fresh signup.

  * No ChumaFlow account with this
    normalized email                 →  fresh signup.

  * ChumaFlow account exists,
    `profile.email_address_verified`
    is False                         →  BLOCK. Send the user to the
    login page with a message
    explaining how to prove the
    email and retry.

  * ChumaFlow account exists,
    `profile.email_address_verified`
    is True                          →  LINK. Both sides have proven
    the same inbox.

Why `email_normalized`: Gmail treats dots and +tags as insignificant,
so `john.doe@gmail.com`, `johndoe@gmail.com`, and `johndoe+shop@gmail.com`
all reach the same inbox. Without normalization, an attacker could
register one spelling while the victim uses another, and ChumaFlow
would treat them as different accounts — the victim's Google sign-in
would never link to their own existing account. See
accounts.email_normalization for the rule.
"""

import logging
import re

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .email_normalization import normalize_email
from .models import User, UserProfile

logger = logging.getLogger(__name__)


class ChumaFlowAccountAdapter(DefaultAccountAdapter):
    """
    Minimal overrides so allauth doesn't own the login and signup pages.
    Our own /login/ and /signup/ views stay authoritative; allauth is
    here only for the OAuth handshake.
    """

    def is_open_for_signup(self, request):
        # Our own /signup/ form handles local signups. Allauth's signup
        # form should never be reachable, but if it somehow is, allow it
        # — it uses the same User model and post-save signal.
        return True

    def get_login_redirect_url(self, request):
        """
        After any successful login — local or social — route through
        the shared router. Uses reverse() rather than a hardcoded path
        so renaming the URL in accounts/urls.py doesn't silently break
        Google sign-in.
        """
        return reverse('post_login_router')


class ChumaFlowSocialAdapter(DefaultSocialAccountAdapter):
    """
    Social sign-in adapter. Three responsibilities:

      1. Enforce the careful-linking rule above.

      2. Give new Google users a predictable username derived from the
         email local part.

      3. Top up the profile from Google's name fields, and clear the
         `must_change_password` flag (Google users never had a temporary
         password to change).
    """

    # ------------------------------------------------------------------
    # 1. Pre-login gate — the careful-linking rule
    # ------------------------------------------------------------------

    def pre_social_login(self, request, sociallogin):
        # Already linked — this is the returning Google user, and
        # allauth's normal login flow proceeds.
        if sociallogin.is_existing:
            return

        google_email = (sociallogin.user.email or "").strip()
        if not google_email:
            # Google didn't return an address. We can't link what we
            # don't have; allauth will create a fresh account.
            return

        # Did Google mark this address verified? Google only issues a
        # successful login for verified addresses, but checking is cheap
        # and explicit.
        google_verified = any(
            getattr(ea, "verified", False)
            for ea in sociallogin.email_addresses
        )
        if not google_verified:
            logger.info(
                "Google returned an unverified address %r; treating as "
                "a fresh signup rather than linking.",
                google_email,
            )
            return

        # Match on the normalized form so Gmail dot/plus variations
        # resolve to the same account. Fall back to case-insensitive
        # exact match for rows whose email_normalized hasn't been
        # backfilled yet (e.g. a user created between the field being
        # added and the migration running).
        normalized = normalize_email(google_email)
        existing = (
            User.objects
            .filter(email_normalized=normalized)
            .select_related("profile")
            .first()
        )
        if existing is None:
            existing = (
                User.objects
                .filter(email__iexact=google_email)
                .select_related("profile")
                .first()
            )

        if existing is None:
            # Fresh signup. Allauth will create the User; save_user()
            # below tops up the profile.
            return

        # --- Existing account. Which side wins? ---
        profile = getattr(existing, "profile", None)
        email_proven = bool(profile and profile.email_address_verified)

        if not email_proven:
            # The ChumaFlow side has never proven the email. It might be
            # a real account with an unverified address, or a squatted
            # claim by someone else. Either way, we don't hand it over.
            #
            # The message points at a concrete next step. A user who IS
            # the real owner can follow it: sign in with the password
            # they set, then prove the email from Settings. A user who
            # doesn't know the password and can't receive the email
            # needs support — hence the WhatsApp hint.
            messages.warning(
                request,
                "An account with this email already exists, but its email "
                "hasn't been verified yet. To sign in with Google: "
                "sign in with your password, open Settings → Security, and "
                "verify your email first. If you didn't create this account, "
                "contact support on WhatsApp.",
            )
            logger.info(
                "Blocked Google link attempt for user %s: "
                "email_address_verified is False (email=%r).",
                existing.pk, google_email,
            )
            raise ImmediateHttpResponse(redirect("login"))

        # Both sides have proven ownership of the same inbox. Link.
        sociallogin.connect(request, existing)
        logger.info(
            "Linked Google identity to existing ChumaFlow account %s "
            "(email_address_verified=True for %r).",
            existing.pk, google_email,
        )
        messages.success(
            request,
            "We linked your Google account to your existing ChumaFlow account.",
        )

        # Notify the account owner out-of-band so an unexpected link
        # can be caught quickly. Best-effort: a broken SMTP server must
        # not abort an otherwise-successful link.
        self._notify_new_signin_method(request, existing)

    # ------------------------------------------------------------------
    # 2. Username generation for new signups
    # ------------------------------------------------------------------

    def populate_username(self, request, user):
        """
        Deterministic username derived from the email local part, with a
        numeric suffix on collision.

            isaacndoka7@gmail.com  →  isaacndoka7
            (collision)            →  isaacndoka72
            …

        Strips characters that aren't valid in a Django username. Falls
        back to "user" for pathological inputs.
        """
        base = (user.email or "").strip().split("@")[0]
        base = re.sub(r"[^\w.]+", "", base) or "user"

        candidate = base
        suffix = 1
        while User.objects.filter(username__iexact=candidate).exists():
            suffix += 1
            candidate = f"{base}{suffix}"

        user.username = candidate
        return candidate

    # ------------------------------------------------------------------
    # 3. Post-signup hook — top up the profile from Google's data
    # ------------------------------------------------------------------

    def save_user(self, request, sociallogin, form=None):
        """
        Called by allauth after it creates a new User from the Google
        payload. The post_save signal on User has already created an
        empty UserProfile + preferences, so we just fill in names and
        flags.
        """
        user = super().save_user(request, sociallogin, form)

        # Keep email_normalized in sync. allauth sets user.email from
        # the Google payload, so this is a cheap way to keep the
        # canonical form correct for every newly-created Google account.
        if user.email:
            normalized = normalize_email(user.email)
            if user.email_normalized != normalized:
                user.email_normalized = normalized
                user.save(update_fields=["email_normalized"])

        profile, _ = UserProfile.objects.get_or_create(user=user)

        updated_fields = []

        if not profile.first_name and user.first_name:
            profile.first_name = user.first_name
            updated_fields.append("first_name")
        if not profile.last_name and user.last_name:
            profile.last_name = user.last_name
            updated_fields.append("last_name")

        # Google verified the address before login. Both flags now flip
        # True — this is one of the few cases where the WhatsApp path
        # and the email path produce the same result, because Google's
        # verification IS an email-based proof.
        if not profile.email_verified:
            profile.email_verified = True
            updated_fields.append("email_verified")
        if not profile.email_address_verified:
            profile.email_address_verified = True
            updated_fields.append("email_address_verified")

        if updated_fields:
            profile.save(update_fields=updated_fields)

        if user.must_change_password:
            user.must_change_password = False
            user.save(update_fields=["must_change_password"])

        return user

    # ------------------------------------------------------------------
    # Helper: security notification on link
    # ------------------------------------------------------------------

    def _notify_new_signin_method(self, request, user):
        """
        Send the account owner an email when a new sign-in method is
        linked. Best-effort: any failure is logged and swallowed.

        Imported locally to avoid a circular import at module load
        (core.notifications imports accounts.models).
        """
        if not user.email:
            return
        try:
            from django.core.mail import send_mail
            from django.conf import settings as django_settings

            send_mail(
                subject="Google sign-in was connected to your ChumaFlow account",
                message=(
                    f"Hi {user.username},\n\n"
                    f"A Google sign-in was just linked to your ChumaFlow "
                    f"account ({user.email}). From now on, signing in with "
                    f"that Google account will log you straight in.\n\n"
                    f"If this wasn't you, sign in with your password and "
                    f"contact support immediately.\n\n"
                    f"— ChumaFlow"
                ),
                from_email=django_settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:
            logger.exception(
                "Failed to send new-sign-in-method notice to user %s", user.pk,
            )