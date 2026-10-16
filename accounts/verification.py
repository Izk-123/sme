# accounts/verification.py
"""
Contact-verification delivery for newly-registered accounts.

Two channels are supported, chosen by the user at signup:

  * Email    — a signed link via Django's send_mail.
  * WhatsApp — the same signed link, delivered through the Meta
               WhatsApp Business Cloud API (credentials from
               settings.WHATSAPP_*).

Both channels carry a signed token that encodes the user id AND the
channel. Encoding the channel matters because "the user clicked a link
we sent" is not the same statement as "the user proved they own their
email address" — a WhatsApp-delivered link proves the phone number, not
the inbox. See accounts.models.UserProfile for the two-flag design and
accounts.adapters.ChumaFlowSocialAdapter for the linking rule that
depends on it.

Public entry point: send_verification(user, channel). Both senders are
best-effort: they return True/False rather than raising, so a signup
can't 500 just because SMTP or WhatsApp is unreachable.

WHATSAPP DELIVERY — the 24-hour window problem
----------------------------------------------
Meta's Cloud API refuses free-form text messages outside a 24-hour
"re-engagement window" that only opens when the recipient messages the
business first. A brand-new signup has never messaged us, so a plain
text verification fails with error 131047.

Two-part fix, both in this file:

  1. Prefer a pre-approved UTILITY template — Meta accepts these
     regardless of the 24h window.
  2. Fall back to free-form text — works inside the window, or on
     Meta's test-number sandbox.

If neither succeeds, the Meta error code is logged with a hint.
"""
import logging

import requests
from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.urls import reverse

logger = logging.getLogger(__name__)


# =============================================================================
# TOKEN CONFIGURATION
# =============================================================================

# Signing salt. Changing this invalidates every outstanding token.
SIGNING_SALT = "accounts.contact-verification"

# Token lifetime. Same for both channels.
VERIFICATION_MAX_AGE = 60 * 60 * 24 * 3  # 3 days


# =============================================================================
# CHANNEL CONSTANTS
# =============================================================================

CHANNEL_EMAIL = "email"
CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_CHOICES = (
    (CHANNEL_EMAIL, "Email"),
    (CHANNEL_WHATSAPP, "WhatsApp"),
)


# =============================================================================
# META GRAPH API CONFIGURATION
# =============================================================================

WHATSAPP_API_VERSION = getattr(settings, "WHATSAPP_API_VERSION", "v23.0")
WHATSAPP_API_TIMEOUT = 10  # seconds

# Meta error codes that mean "you need a template."
TEMPLATE_REQUIRED_CODES = {131047, 131026, 131051}

TEMPLATE_NAME = getattr(settings, "WHATSAPP_VERIFICATION_TEMPLATE_NAME", "")
TEMPLATE_LANGUAGE = getattr(settings, "WHATSAPP_VERIFICATION_TEMPLATE_LANG", "en_US")


# =============================================================================
# TOKEN GENERATION / VERIFICATION
# =============================================================================

def make_verification_token(user, channel=CHANNEL_EMAIL):
    """
    Signed token encoding the user id AND the channel that will deliver
    it. The channel is what VerifyEmailView reads to decide whether to
    set `email_address_verified` (email delivery) or just
    `email_verified` (WhatsApp delivery).

    Defaulting to CHANNEL_EMAIL keeps the signature source-compatible
    with any caller that hasn't been updated yet, but every caller in
    this codebase now passes the channel explicitly.
    """
    return signing.dumps(
        {"user_id": user.pk, "channel": channel},
        salt=SIGNING_SALT,
    )


def verify_token(token, max_age=VERIFICATION_MAX_AGE):
    """
    Return (user_id, channel). Raises signing.SignatureExpired or
    signing.BadSignature as before — callers must catch both.

    Tokens issued before this patch carry no `channel` key. Those are
    treated as channel=None, which VerifyEmailView reads as "proven
    nothing specifically" — it sets `email_verified` but leaves
    `email_address_verified` alone. That's the safe default: an old
    token might have come from either channel, and we can't retro-
    actively guess.
    """
    data = signing.loads(token, salt=SIGNING_SALT, max_age=max_age)
    return data["user_id"], data.get("channel")


def _build_verification_url(user, channel=CHANNEL_EMAIL):
    """
    Absolute URL the user clicks. Uses settings.BASE_URL rather than
    request.build_absolute_uri because WhatsApp sending has no request
    to hand, and behind a reverse proxy build_absolute_uri would pick
    up the internal host rather than the public one.
    """
    token = make_verification_token(user, channel=channel)
    base = getattr(settings, "BASE_URL", "").rstrip("/")
    path = reverse("verify_email", kwargs={"token": token})
    return f"{base}{path}"


# =============================================================================
# PHONE NUMBER NORMALIZATION
# =============================================================================

def normalize_malawi_phone(raw):
    """
    Turn whatever the user typed into E.164-without-plus format, which
    is what the WhatsApp Cloud API expects ("265881234567").

    Accepts all the shapes a Malawian user might reasonably type.
    Returns None if the input doesn't look like a Malawi mobile number.
    """
    if not raw:
        return None

    digits = "".join(ch for ch in raw if ch.isdigit())

    if digits.startswith("265"):
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 9 or digits[0] not in ("8", "9"):
        return None

    return f"265{digits}"


# =============================================================================
# EMAIL SENDER
# =============================================================================

def send_verification_email(user):
    """
    Deliver the verification link by email. Returns True on success,
    False on any failure (already logged). Never raises.

    Always tags the token with CHANNEL_EMAIL — that's what tells the
    view this delivery can legitimately set `email_address_verified`.
    """
    if not user.email:
        return False

    verify_url = _build_verification_url(user, channel=CHANNEL_EMAIL)

    try:
        send_mail(
            subject="Confirm your ChumaFlow account",
            message=(
                f"Hi {user.username},\n\n"
                f"Confirm this is your email address by opening this link:\n"
                f"{verify_url}\n\n"
                f"This link expires in 3 days. If you didn't create this "
                f"account, you can ignore this email.\n"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Failed to send verification email to user %s", user.pk)
        return False


# =============================================================================
# WHATSAPP SENDER (Meta Cloud API)
# =============================================================================

def _post_to_whatsapp(phone_number_id, access_token, payload):
    """
    Thin wrapper around the Meta Graph API POST.

    Returns (response, error_code) — never raises.
    """
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            url, json=payload, headers=headers, timeout=WHATSAPP_API_TIMEOUT,
        )
    except requests.RequestException:
        logger.exception("WhatsApp HTTP call failed")
        return None, None

    if response.status_code < 400:
        return response, None

    try:
        body = response.json()
        err_code = body.get("error", {}).get("code")
    except ValueError:
        err_code = None

    return response, err_code


def _send_whatsapp_template(phone_number_id, access_token, to, verify_url):
    """
    Send via a pre-approved Meta template. Templates bypass the 24h
    window, so this is the correct path for a brand-new signup.
    """
    if not TEMPLATE_NAME:
        return False

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": TEMPLATE_NAME,
            "language": {"code": TEMPLATE_LANGUAGE},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": verify_url}],
            }],
        },
    }

    response, err_code = _post_to_whatsapp(phone_number_id, access_token, payload)

    if response is None or response.status_code >= 400:
        if response is not None:
            logger.error(
                "WhatsApp template send failed: %s %s",
                response.status_code, response.text,
            )
        return False

    return True


def send_verification_whatsapp(user):
    """
    Deliver the verification link via WhatsApp. Returns True on
    success, False on any failure (already logged). Never raises.

    Tags the token with CHANNEL_WHATSAPP — the view uses that to leave
    `email_address_verified` alone. WhatsApp proves the phone number;
    it says nothing about the email inbox, so it must not be counted
    as email verification.
    """
    phone_number_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", None)
    access_token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", None)

    if not (phone_number_id and access_token):
        logger.warning(
            "WhatsApp verification requested for user %s but WHATSAPP_* "
            "credentials are not configured; skipping send.",
            user.pk,
        )
        return False

    primary = user.phone_numbers.filter(is_primary=True).first()
    if primary is None:
        logger.info(
            "User %s has no primary phone number; cannot send WhatsApp "
            "verification.", user.pk,
        )
        return False

    to = normalize_malawi_phone(primary.number)
    if to is None:
        logger.warning(
            "User %s's primary phone (%r) is not a valid Malawi mobile "
            "number; cannot send WhatsApp verification.",
            user.pk, primary.number,
        )
        return False

    verify_url = _build_verification_url(user, channel=CHANNEL_WHATSAPP)

    if TEMPLATE_NAME:
        if _send_whatsapp_template(phone_number_id, access_token, to, verify_url):
            return True
        logger.info(
            "WhatsApp template send failed for user %s; falling back to "
            "free-form text.", user.pk,
        )

    text = (
        f"ChumaFlow: confirm your account by opening this link:\n{verify_url}\n\n"
        f"Expires in 3 days. If you didn't sign up, ignore this message."
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }

    response, err_code = _post_to_whatsapp(phone_number_id, access_token, payload)

    if response is None:
        return False

    if response.status_code >= 400:
        if err_code in TEMPLATE_REQUIRED_CODES:
            logger.warning(
                "WhatsApp requires a template for user %s (Meta code %s). "
                "Register a UTILITY template that takes the verification "
                "URL as a body parameter, then set "
                "WHATSAPP_VERIFICATION_TEMPLATE_NAME in .env. "
                "Raw response: %s",
                user.pk, err_code, response.text,
            )
        else:
            logger.error(
                "WhatsApp verification send failed for user %s: %s %s",
                user.pk, response.status_code, response.text,
            )
        return False

    return True


# =============================================================================
# DISPATCHER
# =============================================================================

def send_verification(user, channel):
    """
    Route to the right sender based on `channel`. See CHANNEL_CHOICES.

    Unknown channel → returns False and logs a warning. Callers read
    the return value to decide whether to show the "check your inbox"
    message or the "couldn't send, try again" warning.
    """
    if channel == CHANNEL_EMAIL:
        return send_verification_email(user)
    if channel == CHANNEL_WHATSAPP:
        return send_verification_whatsapp(user)

    logger.warning("Unknown verification channel %r for user %s", channel, user.pk)
    return False