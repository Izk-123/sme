"""
Email verification for newly-registered accounts.

Uses django.core.signing rather than a dedicated token model - the
token IS the proof (a signed, timestamped user id), so there's nothing
to store or clean up. Tokens expire (see EMAIL_VERIFICATION_MAX_AGE)
rather than being single-use/revocable; that's an acceptable trade for
what this protects (confirming an email address, not authenticating).

WhatsApp confirmation (mentioned alongside email in the original ask)
is NOT implemented here - it needs a provider (Twilio, Africa's
Talking, Meta's WhatsApp Cloud API, etc.) and API credentials, none of
which exist in this project's settings yet. Wire it up the same way as
this module once a provider is chosen, rather than shipping a button
that doesn't actually send anything.
"""
import logging

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.urls import reverse

logger = logging.getLogger(__name__)

SIGNING_SALT = "accounts.email-verification"
EMAIL_VERIFICATION_MAX_AGE = 60 * 60 * 24 * 3  # 3 days


def make_verification_token(user):
    return signing.dumps({"user_id": user.pk}, salt=SIGNING_SALT)


def verify_token(token, max_age=EMAIL_VERIFICATION_MAX_AGE):
    """Returns the user_id encoded in the token, or raises
    signing.BadSignature / signing.SignatureExpired - callers handle those."""
    data = signing.loads(token, salt=SIGNING_SALT, max_age=max_age)
    return data["user_id"]


def send_verification_email(user):
    """
    Best-effort: returns True/False rather than raising, so a signup or
    invitation-acceptance flow doesn't 500 the whole request just
    because SMTP is unreachable or misconfigured. Callers should still
    tell the person what happened (see accounts/views.py).
    """
    if not user.email:
        return False

    token = make_verification_token(user)
    base_url = getattr(settings, "BASE_URL", "").rstrip("/")
    verify_path = reverse("verify_email", kwargs={"token": token})
    verify_url = f"{base_url}{verify_path}"

    try:
        send_mail(
            subject="Confirm your SME Business OS account",
            message=(
                f"Hi {user.username},\n\n"
                f"Confirm this is your email address by opening this link:\n"
                f"{verify_url}\n\n"
                f"This link expires in 3 days. If you didn't create this account, "
                f"you can ignore this email.\n"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
    except Exception:
        # Logged, not raised - see the docstring above.
        logger.exception("Failed to send verification email to user %s", user.pk)
        return False
