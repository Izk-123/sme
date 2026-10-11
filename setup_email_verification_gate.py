"""
==============================================================================
ChumaFlow — email verification gate installer
==============================================================================

Makes email verification actually block the account instead of being an
advisory badge. Adds:

  1.  core/middleware.py                            + EmailVerificationMiddleware
  2.  config/settings.py (auto-located)             + MIDDLEWARE entry
  3.  accounts/views.py                             + VerifyEmailRequiredView
                                                    + tighten VerifyEmailView redirect
  4.  accounts/urls.py                              + verify_email_required
                                                    + resend_verification_email
  5.  templates/accounts/verify_email_required.html (new template)
  6.  Sanity check                                  ResendVerificationEmailView exists

Run from the project root:
    python setup_email_verification_gate.py

Idempotent. UTF-8. Preserves CRLF vs LF.
==============================================================================
"""
from pathlib import Path
import re
import sys


BASE = Path.cwd()


# ------------------------------------------------------------------------------
# Guards
# ------------------------------------------------------------------------------

if not (BASE / "manage.py").exists():
    print(f"ERROR: manage.py not found in {BASE}")
    print("Run this script from the Django project root.")
    sys.exit(1)


# ------------------------------------------------------------------------------
# I/O helpers
# ------------------------------------------------------------------------------

def read(relpath):
    p = BASE / relpath
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write(relpath, content):
    p = BASE / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    print(f"  + {'overwrote' if existed else 'created'} {relpath}")


def append(relpath, block, marker=None):
    p = BASE / relpath
    if not p.exists():
        print(f"  ! {relpath} not found — skipping")
        return False
    t = p.read_text(encoding="utf-8")
    if marker and marker in t:
        print(f"  = {relpath} already has block ({marker!r})")
        return True
    p.write_text(t.rstrip() + "\n\n" + block.lstrip() + "\n", encoding="utf-8")
    print(f"  + appended to {relpath}")
    return True


def ensure_import(relpath, import_line, names=None):
    """Ensure an import is present, optionally augmenting an existing one."""
    p = BASE / relpath
    if not p.exists():
        return False
    t = p.read_text(encoding="utf-8")

    if import_line in t:
        return True

    if names:
        m = re.match(r"from ([\w\.]+) import (.+)", import_line)
        if m:
            source = m.group(1)
            existing = re.search(
                rf"from {re.escape(source)} import ([^\n]+)",
                t,
            )
            if existing:
                have = [x.strip() for x in existing.group(1).split(",")]
                need = [n for n in names if n not in have]
                if need:
                    all_names = have + need
                    new_line = f"from {source} import " + ", ".join(all_names)
                    t = t.replace(existing.group(0), new_line, 1)
                    p.write_text(t, encoding="utf-8")
                    print(f"  + augmented import in {relpath}: + {', '.join(need)}")
                    return True

    m = re.search(r"^(?:from|import)\s", t, re.MULTILINE)
    if m:
        t = t[:m.start()] + import_line + "\n" + t[m.start():]
    else:
        t = import_line + "\n" + t
    p.write_text(t, encoding="utf-8")
    print(f"  + added `{import_line}` to {relpath}")
    return True


def find_file(candidates):
    for rel in candidates:
        if (BASE / rel).exists():
            return rel
    return None


def find_class_body(text, class_name):
    """Return (start, end) char offsets of a class body, or (None, None)."""
    m = re.search(
        rf"^class {re.escape(class_name)}\b[^\n]*:\s*$",
        text,
        re.MULTILINE,
    )
    if not m:
        return None, None
    class_start = m.end()
    next_def = re.search(r"^class\s+\w+|^def\s+\w+", text[class_start:], re.MULTILINE)
    class_end = class_start + next_def.start() if next_def else len(text)
    return class_start, class_end


# ------------------------------------------------------------------------------
# Banner
# ------------------------------------------------------------------------------

print()
print("=" * 72)
print(" Email verification gate installer")
print("=" * 72)
print()


# ==============================================================================
# STEP 1 — core/middleware.py : EmailVerificationMiddleware
# ==============================================================================

print("[1/6] core/middleware.py")

mw_path = find_file(["core/middleware.py", "core/middlewares.py"])
if not mw_path:
    print("  ! core/middleware.py not found — skipping")
else:
    ensure_import(mw_path, "from django.shortcuts import redirect", names=["redirect"])

    mw_class = '''class EmailVerificationMiddleware:
    """
    Blocks authenticated users whose email isn't verified yet, sending
    them to the verification-required page. Placed after
    AuthenticationMiddleware so request.user is populated.

    Users with no email on file are let through — there's nothing to
    verify (invitation acceptance allows phone-only accounts). Staff are
    also let through so /admin/ stays reachable.
    """

    ALLOWED_URL_NAMES = {
        "login",
        "logout",
        "verify_email",               # the link from the email
        "resend_verification_email",  # POST from the verify-required page
        "verify_email_required",      # the page itself
        "change_password",            # so ForcePasswordChange still works
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if not user.is_authenticated or user.is_staff or not user.email:
            return self.get_response(request)

        profile = getattr(user, "profile", None)
        if profile is None or profile.email_verified:
            return self.get_response(request)

        url_name = getattr(request.resolver_match, "url_name", None)
        if url_name not in self.ALLOWED_URL_NAMES:
            return redirect("verify_email_required")

        return self.get_response(request)
'''

    append(mw_path, mw_class, marker="class EmailVerificationMiddleware")


# ==============================================================================
# STEP 2 — settings.py : add to MIDDLEWARE
# ==============================================================================

print("[2/6] settings.py")

settings_path = find_file([
    "config/settings.py",
    "sme_os/settings.py",
    "settings.py",
    "sme_os_starter/settings.py",
])

if not settings_path:
    print("  ! settings.py not found in any common location — skipping")
    print("      add this line to MIDDLEWARE manually, right after")
    print("      ForcePasswordChangeMiddleware:")
    print("        'core.middleware.EmailVerificationMiddleware',")
else:
    print(f"      ({settings_path})")
    src = read(settings_path)

    if "EmailVerificationMiddleware" in src:
        print(f"  = {settings_path} already wires EmailVerificationMiddleware")
    else:
        # Find ForcePasswordChangeMiddleware line and insert after it
        m = re.search(
            r"^([ \t]*)(['\"])core\.middleware\.ForcePasswordChangeMiddleware\2\s*,\s*\n",
            src,
            re.MULTILINE,
        )
        if not m:
            print(f"  ! ForcePasswordChangeMiddleware line not found in {settings_path}")
            print("      add this line to MIDDLEWARE manually, right after")
            print("      ForcePasswordChangeMiddleware:")
            print("        'core.middleware.EmailVerificationMiddleware',")
        else:
            indent = m.group(1)
            quote = m.group(2)
            new_line = f"{indent}{quote}core.middleware.EmailVerificationMiddleware{quote},\n"
            new_src = src[:m.end()] + new_line + src[m.end():]
            (BASE / settings_path).write_text(new_src, encoding="utf-8")
            print(f"  + inserted EmailVerificationMiddleware into MIDDLEWARE")


# ==============================================================================
# STEP 3 — accounts/views.py : VerifyEmailRequiredView + tighten VerifyEmailView
# ==============================================================================

print("[3/6] accounts/views.py")

av = read("accounts/views.py")
if av is None:
    print("  ! accounts/views.py not found — skipping")
else:
    # --- 3a. Add VerifyEmailRequiredView ---
    if "class VerifyEmailRequiredView" in av:
        print("  = accounts/views.py already has VerifyEmailRequiredView")
    else:
        view_class = '''class VerifyEmailRequiredView(LoginRequiredMixin, View):
    """Where EmailVerificationMiddleware sends users with unverified email."""
    template_name = "accounts/verify_email_required.html"

    def get(self, request):
        return render(request, self.template_name)
'''
        append("accounts/views.py", view_class,
               marker="class VerifyEmailRequiredView")

    # --- 3b. Tighten VerifyEmailView redirect ---
    av = read("accounts/views.py")
    start, end = find_class_body(av, "VerifyEmailView")
    if start is None:
        print("  ! class VerifyEmailView not found — skipping redirect tightening")
    else:
        class_body = av[start:end]
        # Look for the last `messages.success(...)` followed by `return redirect(...)`
        # inside the class body.
        block_re = re.compile(
            r"(\n[ \t]*)messages\.success\(\s*request\s*,[^\n]*confirmed[^\n]*\)\s*\n"
            r"([ \t]*)return\s+redirect\([^\n]*?\)\s*(?:\n|$)",
            re.IGNORECASE,
        )
        m = block_re.search(class_body)

        if not m:
            # Try a broader match: any `messages.success + return redirect` pair
            block_re = re.compile(
                r"(\n[ \t]*)messages\.success\([^\n]*\)\s*\n"
                r"([ \t]*)return\s+redirect\([^\n]*?\)\s*(?:\n|$)",
            )
            m = block_re.search(class_body)

        if not m:
            print("  ! could not locate the redirect block inside VerifyEmailView")
            print("      open accounts/views.py and change the ending of")
            print("      VerifyEmailView.get to:")
            print('        messages.success(request, "Email confirmed.")')
            print('        return redirect("home" if request.user.is_authenticated else "login")')
        else:
            indent = m.group(1)
            new_block = (
                f"{indent}messages.success(request, \"Email confirmed.\")\n"
                f"{indent}return redirect(\"home\" if request.user.is_authenticated else \"login\")"
                + "\n"
            )
            new_body = class_body[:m.start()] + new_block + class_body[m.end():]
            new_av = av[:start] + new_body + av[end:]
            (BASE / "accounts/views.py").write_text(new_av, encoding="utf-8")
            print("  + tightened VerifyEmailView redirect")

    # --- 3c. Check that ResendVerificationEmailView exists ---
    av = read("accounts/views.py")
    if "class ResendVerificationEmailView" in av:
        print("  = ResendVerificationEmailView present")
    else:
        print("  ! WARNING: ResendVerificationEmailView not found in accounts/views.py")
        print("      The resend button in the new template won't work until")
        print("      that view exists. Middleware's URL allowlist also")
        print("      references the 'resend_verification_email' name.")


# ==============================================================================
# STEP 4 — accounts/urls.py : register the routes before the token route
# ==============================================================================

print("[4/6] accounts/urls.py")

urls_path = find_file(["accounts/urls.py"])
if not urls_path:
    print("  ! accounts/urls.py not found — skipping")
else:
    src = read(urls_path)

    if "verify_email_required" in src and "resend_verification_email" in src:
        print("  = accounts/urls.py already has both routes")
    else:
        # Find the verify-email token route and insert the two paths before it
        m = re.search(
            r"^([ \t]*)(path\(\s*['\"]verify-email/<str:token>/['\"])",
            src,
            re.MULTILINE,
        )
        if not m:
            # Fallback: try alternate forms
            m = re.search(
                r"^([ \t]*)(path\(\s*['\"][^'\"]*verify[-_]email[^'\"]*<[^>]+>[^'\"]*['\"])",
                src,
                re.MULTILINE,
            )

        if not m:
            print(f"  ! could not locate the verify-email token route in {urls_path}")
            print("      add these two lines manually, BEFORE the token route:")
            print('        path("verify-email/required/",')
            print('             views.VerifyEmailRequiredView.as_view(),')
            print('             name="verify_email_required"),')
            print('        path("verify-email/resend/",')
            print('             views.ResendVerificationEmailView.as_view(),')
            print('             name="resend_verification_email"),')
        else:
            indent = m.group(1)
            new_lines = (
                f'{indent}# Must be registered BEFORE verify-email/<token>/ — the str\n'
                f'{indent}# converter would otherwise swallow "required" as a token.\n'
                f'{indent}path("verify-email/required/",\n'
                f'{indent}     views.VerifyEmailRequiredView.as_view(),\n'
                f'{indent}     name="verify_email_required"),\n'
                f'{indent}path("verify-email/resend/",\n'
                f'{indent}     views.ResendVerificationEmailView.as_view(),\n'
                f'{indent}     name="resend_verification_email"),\n'
            )
            new_src = src[:m.start(1)] + new_lines + src[m.start(1):]
            (BASE / urls_path).write_text(new_src, encoding="utf-8")
            print("  + inserted verify_email_required + resend_verification_email routes")


# ==============================================================================
# STEP 5 — templates/accounts/verify_email_required.html
# ==============================================================================

print("[5/6] templates/accounts/verify_email_required.html")

template = r'''{% extends "base/base_auth.html" %}
{% block title %}Confirm your email — ChumaFlow{% endblock %}

{% block auth_content %}
<div class="pt-4 pb-2">
  <h5 class="card-title text-center pb-0 fs-4 fw-bold">Confirm your email</h5>
  <p class="text-center small text-muted">
    We sent a confirmation link to <strong>{{ user.email }}</strong>.
    Click it to unlock your account.
  </p>
</div>

<div class="rounded p-3 mb-3 d-flex align-items-start gap-3"
     style="background: var(--cf-flow-teal-soft); border: 1px solid var(--cf-flow-teal); color: var(--cf-deep-teal);">
  <i class="bi bi-info-circle flex-shrink-0 mt-1"></i>
  <div class="small">
    Didn't get the email? Check spam, then request a new one below.
    The link expires in 3 days.
  </div>
</div>

<form method="post" action="{% url 'resend_verification_email' %}" class="mb-3">
  {% csrf_token %}
  <button type="submit" class="btn btn-primary w-100">
    <i class="bi bi-envelope me-1"></i> Resend verification email
  </button>
</form>

<div class="d-flex gap-2">
  <a href="{% url 'settings' %}#security" class="btn btn-outline-secondary flex-grow-1">
    <i class="bi bi-gear me-1"></i> Settings
  </a>
  <a href="{% url 'logout' %}" class="btn btn-outline-secondary flex-grow-1">
    <i class="bi bi-box-arrow-right me-1"></i> Sign out
  </a>
</div>
{% endblock %}
'''

# Look for an existing template in either of two layouts
candidates = [
    "templates/accounts/verify_email_required.html",
    "accounts/templates/accounts/verify_email_required.html",
]
existing = next((c for c in candidates if (BASE / c).exists()), None)
target = existing or "templates/accounts/verify_email_required.html"

write(target, template)


# ==============================================================================
# STEP 6 — Final sanity checks
# ==============================================================================

print("[6/6] Final checks")

# Does `settings` URL name exist? The template links to {% url 'settings' %}.
urls_path_scan = read("accounts/urls.py") or ""
other_urls = ""
for rel in [
    "config/urls.py",
    "sme_os/urls.py",
    "sme_os_starter/urls.py",
    "core/urls.py",
]:
    src = read(rel)
    if src:
        other_urls += src

if 'name="settings"' not in urls_path_scan and "name='settings'" not in urls_path_scan:
    if 'name="settings"' not in other_urls and "name='settings'" not in other_urls:
        print("  ! WARNING: no URL named 'settings' was found.")
        print("      The new template links to {% url 'settings' %}#security —")
        print("      either rename the target URL or update the template.")

# Does `profile` have an `email_verified` attribute on the UserProfile model?
accounts_models = read("accounts/models.py") or ""
if "email_verified" not in accounts_models:
    print("  ! WARNING: 'email_verified' field not found in accounts/models.py")
    print("      The middleware checks user.profile.email_verified.")
    print("      Add the field before deploying if it doesn't exist.")

print()
print("=" * 72)
print(" Email verification gate applied.")
print("=" * 72)
print()
print("Files touched:")
print(f"  - {mw_path or 'core/middleware.py (skipped)'}")
print(f"  - {settings_path or 'settings.py (skipped)'}")
print("  - accounts/views.py")
print(f"  - {urls_path or 'accounts/urls.py (skipped)'}")
print(f"  - {target}")
print()
print("Next steps:")
print()
print("  1. Run Django's checks:")
print("       python manage.py check")
print()
print("  2. Start the server and test the flow:")
print("       python manage.py runserver")
print()
print("     a. Sign up a fresh user with an email address")
print("     b. You should immediately land on /verify-email/required/")
print("        instead of the dashboard")
print("     c. Click any other URL — you'll be bounced back to")
print("        /verify-email/required/")
print("     d. Sign out, then click the confirmation link in the email")
print("        (or grab the token from the DB and hit")
print("        /accounts/verify-email/<token>/ manually)")
print("     e. After confirming, log in — you land on the dashboard")
print()
print("  3. Test edge cases:")
print("       - Invitation with phone-only user (no email) -> not gated")
print("       - Staff user (is_staff=True) -> not gated")
print("       - /admin/ remains reachable for staff")
print("       - /change-password/ remains reachable (in allowlist)")
print()
print("  Gotchas from the doc:")
print("    * SMTP failure at signup = account stays stuck on the verify")
print("      page until the resend works. That's the correct behaviour,")
print("      but verify your email backend before going live.")
print("    * Phone-only invited users are never gated. Add an 'Email"
      " verified' column to the Team view if you want them to look")
print("      consistent.")
print()