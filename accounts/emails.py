# accounts/emails.py
"""
DEPRECATED — this module was renamed to accounts.verification when it
gained a second delivery channel (WhatsApp, via the Meta Cloud API).

Kept as a shim so any code still doing `from accounts.emails import ...`
keeps working. New code should import from accounts.verification
directly.

Migration note: the signing salt changed with the rename
("accounts.email-verification" → "accounts.contact-verification"), so
any confirmation tokens issued before this rename no longer validate.
In development that's fine — re-signup or click Resend. If this were
ever applied to a live system with outstanding tokens, verify_token()
would need a grace period that tries both salts.
"""
from .verification import (  # noqa: F401
    CHANNEL_CHOICES,
    CHANNEL_EMAIL,
    CHANNEL_WHATSAPP,
    make_verification_token,
    send_verification,
    send_verification_email,
    send_verification_whatsapp,
    verify_token,
)