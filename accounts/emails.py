# accounts/emails.py
import logging
import smtplib
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
    data = signing.loads(token, salt=SIGNING_SALT, max_age=max_age)
    return data["user_id"]


def send_verification_email(user):
    """
    Best-effort email sending.
    Returns True if sent, False otherwise.
    NEVER raises exceptions (including SystemExit/KeyboardInterrupt).
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
    except BaseException:  # Catch ALL exceptions, including SystemExit
        logger.exception("Failed to send verification email to user %s", user.pk)
        return False
