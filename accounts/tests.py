# accounts/tests.py
"""
Tests for the account-linking rule.

Two suites:

  * NormalizeEmailTests — pure-function tests, no DB, no HTTP. Fast,
    and they pin down the exact canonicalization rules.

  * GoogleLinkingTests — exercise ChumaFlowSocialAdapter.pre_social_login
    with a duck-typed sociallogin double, so the tests don't depend on
    allauth's internal SocialLogin shape. Each test constructs the
    minimum state and asserts a single outcome.

Run with:
    python manage.py test accounts
"""

from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from accounts.email_normalization import normalize_email
from accounts.models import User, UserProfile


# =============================================================================
# Test doubles — duck-typed stand-ins for allauth's own objects
# =============================================================================

class _FakeEmailAddress:
    """
    Stand-in for allauth.account.models.EmailAddress. Only `.verified`
    is read by our adapter.
    """

    def __init__(self, email, verified=True):
        self.email = email
        self.verified = verified


class _FakeSocialUser:
    """Minimal `.user` — our adapter only reads `.email`."""

    def __init__(self, email):
        self.email = email


class _FakeSocialLogin:
    """
    Stand-in for allauth.socialaccount.models.SocialLogin. Only the
    attributes our adapter reads are implemented: `.is_existing`,
    `.user.email`, `.email_addresses`, and `.connect()`.

    `connect()` records the call rather than touching the DB, so tests
    can assert on it without needing allauth's models to exist in a
    consistent state.
    """

    def __init__(self, email, *, verified=True, is_existing=False):
        self.user = _FakeSocialUser(email)
        self.email_addresses = [_FakeEmailAddress(email, verified)]
        self.is_existing = is_existing
        self.connected_to = None

    def connect(self, request, user):
        self.connected_to = user
        self.is_existing = True


def _make_request():
    """
    A bare GET request with `messages` and `session` attached. Both are
    used by our adapter (messages.warning on block,
    messages.success on link) and by allauth's own machinery further
    down the chain.
    """
    rf = RequestFactory()
    request = rf.get("/")
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    request._messages = FallbackStorage(request)
    return request


# =============================================================================
# Test-case helpers
# =============================================================================

def make_user(email, *, email_verified=False, email_address_verified=False):
    """
    Build a User + UserProfile with the given flags set. Username is
    derived from the local part of the email so two distinct emails
    produce two distinct usernames.
    """
    username = email.split("@")[0].replace(".", "_").replace("+", "_")
    user = User.objects.create_user(
        username=username,
        email=email,
        password="test-pw",
    )
    user.email_normalized = normalize_email(email)
    user.save(update_fields=["email_normalized"])

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = email_verified
    profile.email_address_verified = email_address_verified
    profile.save(update_fields=["email_verified", "email_address_verified"])

    return user


# =============================================================================
# Suite 1 — normalize_email()
# =============================================================================

class NormalizeEmailTests(TestCase):
    """Pure-function tests. No DB writes, no HTTP. Fast."""

    def test_empty_inputs(self):
        self.assertEqual(normalize_email(""), "")
        self.assertEqual(normalize_email(None), "")
        self.assertEqual(normalize_email("   "), "")

    def test_lowercases_and_strips(self):
        self.assertEqual(
            normalize_email("  John.Doe@Example.COM  "),
            "john.doe@example.com",
        )

    def test_gmail_dots_are_removed(self):
        self.assertEqual(
            normalize_email("john.doe@gmail.com"),
            normalize_email("johndoe@gmail.com"),
        )

    def test_gmail_plus_tag_is_stripped(self):
        self.assertEqual(
            normalize_email("johndoe+shop@gmail.com"),
            normalize_email("johndoe@gmail.com"),
        )

    def test_googlemail_alias_maps_to_gmail(self):
        self.assertEqual(
            normalize_email("johndoe@googlemail.com"),
            normalize_email("johndoe@gmail.com"),
        )

    def test_gmail_combination(self):
        # dots + tag + googlemail alias all collapse together
        self.assertEqual(
            normalize_email("john.doe+orders@googlemail.com"),
            normalize_email("johndoe@gmail.com"),
        )

    def test_non_gmail_dots_are_significant(self):
        # Dots ARE significant at most providers. Only Gmail collapses
        # them; blanket dot-stripping would merge unrelated accounts.
        self.assertNotEqual(
            normalize_email("john.doe@outlook.com"),
            normalize_email("johndoe@outlook.com"),
        )

    def test_plus_tags_stripped_universally(self):
        # RFC 5233 sub-addressing applies to every provider that
        # implements it — not just Gmail.
        self.assertEqual(
            normalize_email("john+work@outlook.com"),
            normalize_email("john@outlook.com"),
        )

    def test_address_without_at_is_returned_unchanged(self):
        # Defensive: no '@' means we can't safely partition. Returning
        # the input unchanged (still lowercased/stripped) is the right
        # call — this is a matcher, not a validator.
        self.assertEqual(normalize_email("not-an-email"), "not-an-email")


# =============================================================================
# Suite 2 — pre_social_login linking rules
# =============================================================================

class GoogleLinkingTests(TestCase):
    """
    Exercises the decision tree in ChumaFlowSocialAdapter.pre_social_login.

    Each test builds the minimum state and asserts one outcome:
    linked, blocked, or passed through to fresh signup.
    """

    def _adapter(self):
        from accounts.adapters import ChumaFlowSocialAdapter
        return ChumaFlowSocialAdapter()

    def _request(self):
        return _make_request()

    # ------------------------------------------------------------------
    # Scenario 1: account verified by email + Google matches → link
    # ------------------------------------------------------------------

    def test_verified_email_account_links_on_google_match(self):
        existing = make_user(
            "owner@example.com",
            email_verified=True,
            email_address_verified=True,
        )

        sl = _FakeSocialLogin("owner@example.com")

        # Should not raise.
        self._adapter().pre_social_login(self._request(), sl)

        # connect() is called with the existing user.
        self.assertEqual(sl.connected_to, existing)

    # ------------------------------------------------------------------
    # Scenario 2: account verified only by WhatsApp → block
    # ------------------------------------------------------------------

    def test_whatsapp_only_account_is_blocked(self):
        make_user(
            "wa-only@example.com",
            email_verified=True,            # contact confirmed
            email_address_verified=False,   # but NOT via email
        )

        sl = _FakeSocialLogin("wa-only@example.com")

        from allauth.core.exceptions import ImmediateHttpResponse

        with self.assertRaises(ImmediateHttpResponse):
            self._adapter().pre_social_login(self._request(), sl)

        # It must not have linked anything.
        self.assertIsNone(sl.connected_to)

    # ------------------------------------------------------------------
    # Scenario 3: account never verified → block
    # ------------------------------------------------------------------

    def test_unverified_account_is_blocked(self):
        make_user(
            "unverified@example.com",
            email_verified=False,
            email_address_verified=False,
        )

        sl = _FakeSocialLogin("unverified@example.com")

        from allauth.core.exceptions import ImmediateHttpResponse

        with self.assertRaises(ImmediateHttpResponse):
            self._adapter().pre_social_login(self._request(), sl)

        self.assertIsNone(sl.connected_to)

    # ------------------------------------------------------------------
    # Scenario 4: Gmail variants resolve to one account
    # ------------------------------------------------------------------

    def test_gmail_variants_match_the_same_account(self):
        """
        The victim registered as john.doe@gmail.com and proved the
        email. A Google identity for johndoe@gmail.com (same inbox)
        must resolve to the SAME account, not a fresh signup.
        """
        existing = make_user(
            "john.doe@gmail.com",
            email_verified=True,
            email_address_verified=True,
        )

        # Sanity check: the canonical forms are equal.
        self.assertEqual(
            existing.email_normalized,
            normalize_email("johndoe@gmail.com"),
        )

        sl = _FakeSocialLogin("johndoe@gmail.com")
        self._adapter().pre_social_login(self._request(), sl)

        self.assertEqual(sl.connected_to, existing)

    def test_gmail_plus_tag_matches_the_same_account(self):
        """
        Same as above, but with a +tag on the Google address. The
        tag is stripped by normalization, so the match still hits.
        """
        existing = make_user(
            "johndoe@gmail.com",
            email_verified=True,
            email_address_verified=True,
        )

        sl = _FakeSocialLogin("johndoe+shop@gmail.com")
        self._adapter().pre_social_login(self._request(), sl)

        self.assertEqual(sl.connected_to, existing)

    # ------------------------------------------------------------------
    # Scenario 5: two different emails → two separate users
    # ------------------------------------------------------------------

    def test_different_emails_do_not_merge(self):
        """
        Two Google identities with distinct addresses produce two
        distinct ChumaFlow accounts. The linking rule must never
        collapse unrelated people.
        """
        alice = make_user(
            "alice@example.com",
            email_verified=True,
            email_address_verified=True,
        )
        bob = make_user(
            "bob@example.com",
            email_verified=True,
            email_address_verified=True,
        )

        self.assertNotEqual(alice.pk, bob.pk)
        self.assertNotEqual(alice.email_normalized, bob.email_normalized)

        sl_alice = _FakeSocialLogin("alice@example.com")
        self._adapter().pre_social_login(self._request(), sl_alice)
        self.assertEqual(sl_alice.connected_to, alice)

        sl_bob = _FakeSocialLogin("bob@example.com")
        self._adapter().pre_social_login(self._request(), sl_bob)
        self.assertEqual(sl_bob.connected_to, bob)

    # ------------------------------------------------------------------
    # Additional edge cases
    # ------------------------------------------------------------------

    def test_already_linked_social_login_is_passed_through(self):
        """
        A returning Google user (sociallogin.is_existing=True) must not
        be re-gated — that would break every subsequent sign-in.
        """
        sl = _FakeSocialLogin(
            "returning@example.com",
            is_existing=True,
        )

        # Should not raise, should not attempt to connect.
        self._adapter().pre_social_login(self._request(), sl)
        self.assertIsNone(sl.connected_to)

    def test_unverified_google_email_is_not_linked(self):
        """
        If Google itself says the address isn't verified, we don't
        treat it as proof of anything — even if a ChumaFlow account
        with that address exists and is email-proven.
        """
        make_user(
            "suspicious@example.com",
            email_verified=True,
            email_address_verified=True,
        )

        sl = _FakeSocialLogin("suspicious@example.com", verified=False)

        # Should not raise (treated as fresh signup path), should not
        # link to the existing account.
        self._adapter().pre_social_login(self._request(), sl)
        self.assertIsNone(sl.connected_to)

    def test_no_matching_account_passes_through(self):
        """
        A Google identity with an email that has no ChumaFlow account
        must not be blocked — allauth will create a fresh account.
        """
        sl = _FakeSocialLogin("brand-new@example.com")

        # Should not raise.
        self._adapter().pre_social_login(self._request(), sl)
        self.assertIsNone(sl.connected_to)  # nothing to connect to