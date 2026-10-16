# accounts/email_normalization.py
"""
Canonical form of an email address, for equality comparison.

The problem this solves: Gmail treats `john.doe@gmail.com`,
`johndoe@gmail.com`, and `johndoe+shop@gmail.com` as the same inbox.
So does Fastmail, Proton, Outlook (with +tags), and most modern
providers. If ChumaFlow stores them as three different strings, a
returning user who signs in with a slightly different spelling gets a
second, empty account — and worse, an attacker who knows the victim's
inbox can claim one spelling while the victim uses another.

`normalize_email()` collapses all of those into one string that can be
compared, stored, and indexed.

Deliberately NOT done here:
  * Yahoo-style "dash addressing" (user-shop@yahoo.com) — Yahoo
    deprecated it, and matching on it would create false positives
    for legitimate users whose address happens to contain a dash.
  * Plus-tag stripping for providers that treat tags as significant.
    Currently we strip tags universally, on the assumption that the
    user's intent — "this is the same inbox" — is more important
    than the provider's local-part semantics.
"""


def normalize_email(email):
    """
    Return a canonical form of an email address for equality comparison.

    Rules, in order:
      1. Lowercase the whole thing (email local parts are case-
         insensitive in practice; no major provider distinguishes).
      2. Strip whitespace.
      3. Remove the sub-address tag: everything from the first '+'
         onward in the local part. RFC 5233.
      4. For Gmail (and its googlemail.com alias): remove all '.' from
         the local part, and canonicalise googlemail.com → gmail.com.

    Returns "" for empty input, and returns the input unchanged if it
    doesn't contain an '@'. This function is used for matching, not
    validation — it should never raise, only give a best-effort answer.
    """
    if not email:
        return ""

    email = email.strip().lower()

    if "@" not in email:
        return email

    local, _, domain = email.partition("@")
    if not local or not domain:
        return email

    # RFC 5233 sub-addressing: user+anything@provider → user@provider.
    if "+" in local:
        local = local.split("+", 1)[0]

    # Gmail's own rules. googlemail.com is a legacy alias with identical
    # delivery, so both spellings map to gmail.com.
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
        domain = "gmail.com"

    return f"{local}@{domain}"