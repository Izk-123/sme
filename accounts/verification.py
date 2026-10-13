# accounts/verification.py
"""
Contact-verification delivery for newly-registered accounts.

Two channels are supported, chosen by the user at signup:

  * Email    — a signed link via Django's send_mail.
  * WhatsApp — the same signed link, delivered through the Meta
               WhatsApp Business Cloud API (credentials from
               settings.WHATSAPP_*).

Both channels carry the *same* token. django.core.signing encodes
{user_id} with a salt, so there is no row to store or clean up — the
token IS the proof. Tokens expire (see VERIFICATION_MAX_AGE) rather
than being single-use/revocable; that's an acceptable trade for what
this protects (confirming a contact address, not authenticating).

Public entry point: send_verification(user, channel). The channel-
specific senders are exposed so a future "resend by the other channel"
button can force one, but the dispatcher is what callers should use.

Both senders are best-effort: they return True/False rather than
raising, so a signup or invitation-acceptance flow can't 500 just
because SMTP or the WhatsApp API is unreachable. Callers must still
tell the user what happened — see accounts/views.py.

WHATSAPP DELIVERY — the 24-hour window problem
----------------------------------------------
Meta's Cloud API refuses free-form text messages outside a 24-hour
"re-engagement window" that only opens when the *recipient* messages
the business first. A brand-new signup has never messaged us, so
sending them plain text fails with error 131047.

The fix has two parts, both in this file:

  1. Prefer a pre-approved *template* (WHATSAPP_VERIFICATION_TEMPLATE_NAME)
     — Meta accepts templates regardless of the 24h window, and
     verification is a textbook UTILITY template use case.
  2. Fall back to free-form text — works within the window, or on
     Meta's test-number sandbox where the allowlist relaxes the rule.

If neither path succeeds, we log the exact Meta error code (see
TEMPLATE_REQUIRED_CODES) so the operator knows to register a template,
rather than staring at a generic "send failed" message.

Not yet implemented (separate feature, needs the webhook view already
set up at /payments/webhooks/whatsapp/):
  * Inbound WhatsApp — receiving replies, delivery/read receipts, or
    a "STOP" opt-out. That's the job of payments.views.WhatsAppWebhookView.
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

# Signing salt. Changing this invalidates every outstanding token —
# don't, unless you actually want old links to stop working.
SIGNING_SALT = "accounts.contact-verification"

# Token lifetime. 3 days is a deliberate trade-off: long enough that a
# user who checks email slowly still gets in, short enough that a leaked
# link has a bounded blast radius. Same value applies to both channels.
VERIFICATION_MAX_AGE = 60 * 60 * 24 * 3  # 3 days


# =============================================================================
# CHANNEL CONSTANTS
# =============================================================================

# Plain strings (not an enum) so they can be used directly in model
# choice fields without import gymnastics. Must stay in sync with
# UserProfile.VERIFICATION_CHANNEL_CHOICES in accounts/models/profile.py.
CHANNEL_EMAIL = "email"
CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_CHOICES = (
    (CHANNEL_EMAIL, "Email"),
    (CHANNEL_WHATSAPP, "WhatsApp"),
)


# =============================================================================
# META GRAPH API CONFIGURATION
# =============================================================================

# Graph API version. Meta deprecates versions on a rolling ~2-year cycle
# and will hard-reject calls to a dead version. v19.0 (the previous
# hardcoded value) is retired — always read from settings so a future
# bump is a .env change, not a code change.
#
# Current version list: https://developers.facebook.com/docs/graph-api/changelog
WHATSAPP_API_VERSION = getattr(settings, "WHATSAPP_API_VERSION", "v23.0")

# Per-request timeout. Matches EMAIL_TIMEOUT's rationale: a slow Meta
# endpoint must never hang a Gunicorn worker indefinitely.
WHATSAPP_API_TIMEOUT = 10  # seconds

# Meta error codes that all mean the same thing — "you need a template."
# When we see one of these, we log a hint pointing to the template setup
# instructions rather than a raw API error.
#
#   131047 — Re-engagement message (recipient hasn't messaged recently)
#   131026 — Message undeliverable  (usually also window-related)
#   131051 — Unsupported message type (rare, but observed in the wild)
TEMPLATE_REQUIRED_CODES = {131047, 131026, 131051}

# Name of a Meta-approved UTILITY template that accepts the verification
# URL as a body parameter {{1}}. Register one in Meta Business Suite:
#
#   Category:  Utility
#   Body:      "Confirm your ChumaFlow account by opening this link:
#               {{1}}
#
#               This link expires in 3 days. If you didn't sign up,
#               ignore this message."
#
# Then set WHATSAPP_VERIFICATION_TEMPLATE_NAME in .env.
# If unset, we skip the template attempt and go straight to text.
TEMPLATE_NAME = getattr(settings, "WHATSAPP_VERIFICATION_TEMPLATE_NAME", "")
TEMPLATE_LANGUAGE = getattr(settings, "WHATSAPP_VERIFICATION_TEMPLATE_LANG", "en_US")


# =============================================================================
# TOKEN GENERATION / VERIFICATION
# =============================================================================

def make_verification_token(user):
    """
    Signed, timestamped user-id token. The proof for both channels.

    signing.dumps produces a URL-safe string embedding {"user_id": pk}
    plus a timestamp — no database row required. verify_token() reverses
    this and raises on tampering or expiry.
    """
    return signing.dumps({"user_id": user.pk}, salt=SIGNING_SALT)


def verify_token(token, max_age=VERIFICATION_MAX_AGE):
    """
    Return the user_id encoded in the token, or raise one of:

      * signing.SignatureExpired — token is valid but older than max_age
      * signing.BadSignature     — token was tampered with or signed
                                   with a different salt

    Callers (accounts.views.VerifyEmailView) catch these and show a
    specific error to the user, so the exception types matter.
    """
    data = signing.loads(token, salt=SIGNING_SALT, max_age=max_age)
    return data["user_id"]


def _build_verification_url(user):
    """
    Absolute URL the user clicks. Uses settings.BASE_URL rather than
    request.build_absolute_uri for two reasons:

      (a) WhatsApp sending has no request object to hand, so we can't
          call build_absolute_uri anyway.
      (b) Behind a reverse proxy (Nginx → Gunicorn), build_absolute_uri
          would pick up the internal host header, not the public domain.
          BASE_URL is set explicitly in .env for exactly this reason.
    """
    token = make_verification_token(user)
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

    Accepts all the shapes a Malawian user might reasonably type:

        0881234567      -> 265881234567
        088 123 4567    -> 265881234567
        991234567       -> 265991234567
        +265881234567   -> 265881234567
        265881234567    -> 265881234567

    Returns None if the input doesn't look like a Malawi mobile number.
    After stripping country code and leading zero, the remaining string
    must be 9 digits starting with '8' or '9' — the Airtel 088/089 and
    TNM 098/099 ranges. Landlines (01...) are intentionally rejected;
    they can't receive WhatsApp messages.

    Callers treat None as a validation failure — see SignupForm for the
    user-facing error, and send_verification_whatsapp for the internal
    "can't send to this number" guard.
    """
    if not raw:
        return None

    # Strip everything that isn't a digit (spaces, +, dashes, parens).
    digits = "".join(ch for ch in raw if ch.isdigit())

    # Drop the Malawi country code if present, then the leading zero if
    # still there. Order matters: "+265 088..." is malformed but the
    # sequence above still normalizes it correctly to "26588...".
    if digits.startswith("265"):
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]

    # Airtel (088/089) and TNM (098/099) — the only two mobile carriers
    # in Malawi. Anything else (1xx landline, wrong length) is rejected.
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

    Refuses to send if the user has no email on file — that's the
    "WhatsApp-only signup" case, and the caller shouldn't have routed
    us here (SignupForm.clean() enforces the "required iff chosen"
    rule, so this is a belt-and-braces guard for edge cases).
    """
    if not user.email:
        return False

    verify_url = _build_verification_url(user)

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
        # Broad catch is deliberate: a broken SMTP server, DNS failure,
        # or authentication error must all return False so the signup
        # flow can show "couldn't send, try again" instead of 500ing.
        logger.exception("Failed to send verification email to user %s", user.pk)
        return False


# =============================================================================
# WHATSAPP SENDER (Meta Cloud API)
# =============================================================================

def _post_to_whatsapp(phone_number_id, access_token, payload):
    """
    Thin wrapper around the Meta Graph API POST.

    Returns a tuple (response, error_code):
      * On success:    (response, None)
      * On HTTP error: (response, meta_error_code_or_None)
      * On network failure: (None, None)

    Never raises requests exceptions — callers log and return False.
    Isolating the HTTP + error-parsing logic here keeps the two senders
    (template, text) focused on their payloads.
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

    # Meta returns a JSON body on error. The "code" field is what we
    # use to distinguish "needs a template" from "bad credentials".
    try:
        body = response.json()
        err_code = body.get("error", {}).get("code")
    except ValueError:
        # Non-JSON error response (proxy error, HTML, etc.) — not
        # unusual when the API is having a bad day.
        err_code = None

    return response, err_code


def _send_whatsapp_template(phone_number_id, access_token, to, verify_url):
    """
    Send the verification link via a pre-approved Meta template.

    This is the *correct* path for a brand-new signup, because the 24h
    re-engagement window has never been opened (the user has never
    messaged the business). Templates bypass that window entirely.

    Returns True on success, False on any failure or if no template is
    configured (so the caller can fall through to the text attempt).
    """
    if not TEMPLATE_NAME:
        # No template configured — this is expected during initial
        # setup. The text path below will still work for users who are
        # within the 24h window, or on a test number.
        return False

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": TEMPLATE_NAME,
            "language": {"code": TEMPLATE_LANGUAGE},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        # Positional parameter {{1}} in the template body.
                        {"type": "text", "text": verify_url},
                    ],
                },
            ],
        },
    }

    response, err_code = _post_to_whatsapp(phone_number_id, access_token, payload)

    if response is None:
        return False
    if response.status_code >= 400:
        logger.error(
            "WhatsApp template send failed: %s %s",
            response.status_code, response.text,
        )
        return False

    return True


def send_verification_whatsapp(user):
    """
    Deliver the verification link over WhatsApp via Meta's Cloud API.

    Returns True on success, False on any failure (already logged).
    Never raises.

    Preconditions checked here so callers don't have to:
      * user has a primary phone number on file, and it normalizes to a
        valid Malawi mobile number,
      * WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN are set.

    Strategy (two attempts, in order):

      1. Template send — works for every user, including brand-new
         signups outside the 24h re-engagement window. Only attempted
         if WHATSAPP_VERIFICATION_TEMPLATE_NAME is set.

      2. Free-form text — works within the 24h window (user messaged us
         recently), or on Meta's test-number sandbox where the recipient
         allowlist relaxes the window rule. This is why it's still kept
         as a fallback: during initial development without a registered
         template, it's the only path that works.

    If both attempts fail with a template-required error code, we log a
    specific hint pointing at the template setup instructions rather
    than the raw Meta error.
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
        # Caller should have caught this (ResendVerificationEmailView
        # does — see the pre-flight check there). Logging for diagnosis.
        logger.info(
            "User %s has no primary phone number; cannot send WhatsApp "
            "verification.",
            user.pk,
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

    verify_url = _build_verification_url(user)

    # -------------------------------------------------------------------
    # Attempt 1: template (works for every user — the "correct" path)
    # -------------------------------------------------------------------
    if TEMPLATE_NAME:
        if _send_whatsapp_template(phone_number_id, access_token, to, verify_url):
            return True
        logger.info(
            "WhatsApp template send failed for user %s; falling back to "
            "free-form text.",
            user.pk,
        )

    # -------------------------------------------------------------------
    # Attempt 2: free-form text (works inside the 24h window)
    # -------------------------------------------------------------------
    text = (
        f"ChumaFlow: confirm your account by opening this link:\n{verify_url}\n\n"
        f"Expires in 3 days. If you didn't sign up, ignore this message."
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        # preview_url=False: the link is a text link, not a rich preview.
        # Meta would otherwise try to fetch and render a card, which
        # adds latency and can fail if the verification page isn't
        # publicly reachable at send time.
        "text": {"preview_url": False, "body": text},
    }

    response, err_code = _post_to_whatsapp(phone_number_id, access_token, payload)

    if response is None:
        # Network failure — already logged inside _post_to_whatsapp.
        return False

    if response.status_code >= 400:
        if err_code in TEMPLATE_REQUIRED_CODES:
            # The most actionable log line in this file. This is the
            # "brand-new signup, never messaged us" case — the fix is
            # to register the template, not to retry the text send.
            logger.warning(
                "WhatsApp requires a template for user %s (Meta code %s). "
                "Register a UTILITY template that takes the verification "
                "URL as a body parameter, then set "
                "WHATSAPP_VERIFICATION_TEMPLATE_NAME in .env. "
                "Raw response: %s",
                user.pk, err_code, response.text,
            )
        else:
            # Some other error — bad credentials, invalid recipient,
            # rate limit, etc. Log the full body; Meta's error messages
            # are actually quite good.
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

    Unknown channel → returns False and logs a warning. This fails
    visibly rather than silently emailing the wrong person or no-op'ing
    without a trace — which is the whole reason the constant set exists.

    Both senders are best-effort: they return True/False rather than
    raising. Callers read the return value to decide whether to show
    the "check your inbox" message or the "couldn't send, try again"
    warning — see SignupView and ResendVerificationEmailView.
    """
    if channel == CHANNEL_EMAIL:
        return send_verification_email(user)
    if channel == CHANNEL_WHATSAPP:
        return send_verification_whatsapp(user)

    logger.warning("Unknown verification channel %r for user %s", channel, user.pk)
    return False