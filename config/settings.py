"""
Django settings for ChumaFlow (SME Business OS).

Single settings file that works for both development and production.
Environment-specific behaviour is controlled via .env variables.

Minimum .env for PRODUCTION:
    DEBUG=False
    SECRET_KEY=<strong-random-key>
    ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
    DB_NAME=...  DB_USER=...  DB_PASSWORD=...  DB_HOST=...  DB_PORT=...
    (DB_ENGINE is optional — production defaults to PostgreSQL.)

Optional:
    USE_REDIS=True/False, REDIS_HOST, REDIS_PORT
    CSRF_TRUSTED_ORIGINS=https://yourdomain.com
    EMAIL_* , PAYCHANGU_* , WHATSAPP_* , BASE_URL, SECURE_SSL_REDIRECT
    GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET
"""

import os
from pathlib import Path
from dotenv import load_dotenv


# =============================================================================
# 1. PATH SETUP & ENVIRONMENT VARIABLES
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean env variable: '1'/'true'/'yes'/'on' → True."""
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ('true', '1', 'yes', 'on')


def env_list(name: str, default: str = '') -> list:
    """Read a comma-separated env variable into a list."""
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(',') if item.strip()]


# =============================================================================
# 2. SECURITY & DEBUG SETTINGS
# =============================================================================

DEBUG = env_bool('DEBUG', default=True)

# SECRET_KEY: safe fallback in dev, hard-fail in production
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-dev-only-key-change-me'
    else:
        raise ValueError("SECRET_KEY must be set in .env when DEBUG=False")

# ALLOWED_HOSTS: dev gets safe defaults, production must set explicitly
ALLOWED_HOSTS = env_list('ALLOWED_HOSTS')
if not ALLOWED_HOSTS:
    if DEBUG:
        ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']
    else:
        raise ValueError("ALLOWED_HOSTS must be set in .env when DEBUG=False")

# Trusted origins for CSRF (required behind HTTPS proxies / custom domains)
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')


# =============================================================================
# 3. APPLICATION DEFINITION
# =============================================================================

INSTALLED_APPS = [
    # Unfold admin theme (must come first)
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',

    # Django core
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Sites framework. Required by django-allauth: it identifies "this
    # site" when constructing OAuth callback URLs and outgoing mail.
    # A single Site row (id=1) is created by the initial migration —
    # edit its domain in the Django admin so it matches your host.
    'django.contrib.sites',

    # Form rendering app. Required because we set FORM_RENDERER to
    # TemplatesSetting — the built-in widget templates (attrs.html etc.)
    # resolve through this app.
    'django.forms',

    # django-allauth — the OAuth dance lives here. Only used for
    # social sign-in; our own /signup/ and /login/ pages stay in charge
    # of the local (username + password) flows.
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',

    # Third-party / async
    'channels',

    # Custom apps
    'accounts',
    'subscriptions',
    'payments',
    'organizations',
    'customers',
    'sales',
    'expenses',
    'reports',
    'suppliers',
    'core',
]

UNFOLD = {
    "SITE_TITLE": "ChumaFlow",
    "SITE_HEADER": "ChumaFlow",
    "SITE_SYMBOL": "waves",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
}


# =============================================================================
# 3b. FORM RENDERING
# =============================================================================
#
# Django has TWO template engines running side by side:
#
#   1. The main one from TEMPLATES below. Used for normal page renders
#      (base.html, login.html, settings.html, …). It sees BOTH the
#      project-root `templates/` directory (via DIRS) AND every app's
#      `templates/` directory (via APP_DIRS).
#
#   2. The FORM RENDERER's engine. Used when Django renders a form
#      widget's own template — e.g. ProfilePhotoWidget.template_name
#      → "accounts/widgets/profile_photo_drop.html".
#
# By default the form renderer builds its own mini-engine with
# `DIRS=[]` and `APP_DIRS=True`, so it can find templates inside app
# `templates/` folders but NOT anything in the project-root
# `templates/` directory. It also starts with empty OPTIONS, which
# means no context_processors and no `builtins` — a widget template
# that does {% load money %} would blow up under the default renderer
# even if it was findable.
#
# Switching to TemplatesSetting makes the form renderer delegate to
# django.template.loader.get_template(), which uses the FULL TEMPLATES
# configuration above. Widgets then resolve exactly like every other
# template in the project: same DIRS, same APP_DIRS, same builtins,
# same context processors.
#
# The one requirement: 'django.forms' must be in INSTALLED_APPS
# (done above), or the built-in widget templates (attrs.html etc.)
# stop resolving.
#
FORM_RENDERER = 'django.forms.renderers.TemplatesSetting'


# =============================================================================
# 4. AUTHENTICATION & USER MODEL
# =============================================================================

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "post_login_router"
LOGOUT_REDIRECT_URL = "login"


# =============================================================================
# 4b. AUTH BACKENDS & SOCIAL SIGN-IN
# =============================================================================

AUTHENTICATION_BACKENDS = [
    # Default Django backend — handles username + password.
    'django.contrib.auth.backends.ModelBackend',
    # allauth backend — handles social sign-in and its own sessions.
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Sites framework ID. On a fresh project there's exactly one Site row
# (id=1, domain="example.com"). Change its domain to your real host in
# the Django admin (/admin/sites/site/1/change/) before testing Google
# sign-in — allauth builds the OAuth callback URL from it, so if it
# still says example.com, Google will redirect there and nothing works.
SITE_ID = 1

# --- allauth behaviour ------------------------------------------------------
#
# We are not using allauth's own login or signup pages, only its social
# provider plumbing. The flags below enforce that intent.
ACCOUNT_LOGIN_METHODS = {'email'}          # not used, but avoids warnings
ACCOUNT_SIGNUP_FIELDS = []                 # we never call allauth's signup form
ACCOUNT_EMAIL_VERIFICATION = 'none'        # our own verification owns this
ACCOUNT_UNIQUE_EMAIL = True

# Point allauth at our templates for the third-party error page and the
# social signup conflict page.
ACCOUNT_ADAPTER = 'accounts.adapters.ChumaFlowAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.ChumaFlowSocialAdapter'

# Let allauth create a brand-new User from the Google payload. We then
# top up the profile (in the adapter) and, if the new user has no
# Membership yet, route them through /complete-signup/ to pick a
# business name. See accounts.adapters.ChumaFlowSocialAdapter.
SOCIALACCOUNT_AUTO_SIGNUP = True

# CRITICAL — careful account linking.
#
# Allauth's default would connect a Google identity to an existing
# ChumaFlow account by matching email addresses. That's unsafe: a
# person can type victim@example.com into our signup form, never
# verify it, and abandon the account. Later somebody else registers
# a Google account for the same address (Google verifies it, so
# they're provably the owner NOW) and allauth would silently hand
# them access to the first person's ChumaFlow account.
#
# We disable allauth's auto-link entirely. Linking happens only inside
# ChumaFlowSocialAdapter.pre_social_login(), and only when BOTH sides
# have verified the email.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = False

# Ask Google only for the scopes we actually consume.
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': os.getenv('GOOGLE_OAUTH_CLIENT_ID', ''),
            'secret':    os.getenv('GOOGLE_OAUTH_CLIENT_SECRET', ''),
            'key':       '',
        },
        'SCOPE': ['profile', 'email'],
        # online = no refresh token, which is all we need. We are
        # identifying users, not acting on their behalf.
        'AUTH_PARAMS': {
            'access_type': 'online',
            # Force the account chooser even if the user is already
            # signed into one Google account — avoids the "signed
            # into the wrong account" surprise on shared devices.
            'prompt': 'select_account',
        },
        # PKCE hardens the code exchange against interception.
        'OAUTH_PKCE_ENABLED': True,
    },
}


# =============================================================================
# 5. MIDDLEWARE
# =============================================================================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # serves static in prod
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',

    # allauth must sit right after AuthenticationMiddleware: it attaches
    # request.user-facing state that our own middleware below reads.
    'allauth.account.middleware.AccountMiddleware',

    # Custom middleware — order matters
    'core.middleware.CurrentMembershipMiddleware',
    'subscriptions.middleware.SubscriptionMiddleware',
    'core.middleware.ForcePasswordChangeMiddleware',

    'core.middleware.EmailVerificationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# =============================================================================
# 6. ASGI / CHANNELS (Real-time notifications)
# =============================================================================

ASGI_APPLICATION = 'config.asgi.application'

# Default: Redis in production, InMemory in dev. Override with USE_REDIS.
if env_bool('USE_REDIS', default=not DEBUG):
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [
                    (os.getenv('REDIS_HOST', '127.0.0.1'),
                     int(os.getenv('REDIS_PORT', 6379)))
                ],
                "capacity": 1500,   # max queued messages per channel
                "expiry": 10,       # message expiry (seconds)
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }


# =============================================================================
# 7. URLS, TEMPLATES, WSGI
# =============================================================================

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.low_stock_processor',
            ],
            'builtins': [
                'core.templatetags.money',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# =============================================================================
# 8. DATABASE
# =============================================================================

# Engine resolution:
#   1. If DB_ENGINE is explicitly set in .env, honour it ('postgresql' | 'sqlite').
#   2. Otherwise, default by environment:
#        DEBUG=True  → SQLite      (zero-config local dev)
#        DEBUG=False → PostgreSQL  (production never silently uses SQLite)
#
# Production with Postgres selected but missing credentials → hard crash,
# so an empty SQLite file can never masquerade as a working database.

_db_engine = os.getenv('DB_ENGINE', '').strip().lower()
if not _db_engine:
    _db_engine = 'sqlite' if DEBUG else 'postgresql'

if _db_engine == 'postgresql':
    _db_name = os.getenv('DB_NAME')
    _db_user = os.getenv('DB_USER')
    _db_pass = os.getenv('DB_PASSWORD')

    _missing = [
        name for name, val in (
            ('DB_NAME', _db_name),
            ('DB_USER', _db_user),
            ('DB_PASSWORD', _db_pass),
        ) if not val
    ]
    if _missing and not DEBUG:
        raise ValueError(
            "PostgreSQL is the production database but these .env values "
            f"are missing: {', '.join(_missing)}"
        )

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': _db_name,
            'USER': _db_user,
            'PASSWORD': _db_pass,
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': 60,          # reuse connections across requests
            'OPTIONS': {
                'connect_timeout': 10,
            },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# =============================================================================
# 9. PASSWORD VALIDATION
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# =============================================================================
# 10. INTERNATIONALIZATION
# =============================================================================

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Blantyre'
USE_I18N = True
USE_TZ = True


# =============================================================================
# 11. STATIC & MEDIA FILES
# =============================================================================

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Whitenoise in production.
#
# CompressedManifestStaticFilesStorage raises ValueError → HTTP 500 whenever a
# template references a static file that wasn't collected. CompressedStaticFilesStorage
# compresses + caches headers but 404s missing files instead of exploding.
#
# If you want the extra layer of cache-busting hashes, switch to
# CompressedManifestStaticFilesStorage — but ONLY after confirming that
# `python manage.py collectstatic` reports zero missing files.
if not DEBUG:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }
    # Silence the legacy setting name warning on Django 4.2+ (it's still
    # read for backwards compatibility if STORAGES is absent).
    STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"


# =============================================================================
# 12. EMAIL CONFIGURATION
# =============================================================================

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'mail.pritechmw.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 465))
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', default=True)
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', default=False)
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)

# Prevents Gunicorn worker from hanging if SMTP is unreachable
EMAIL_TIMEOUT = 10

# Absolute base URL used in emails, WhatsApp messages, invite links,
# and verification links. Must be the *public* URL — behind a reverse
# proxy, request.build_absolute_uri would pick up the internal host,
# so accounts.verification._build_verification_url reads this instead.
BASE_URL = os.getenv('BASE_URL', 'http://localhost:8000')


# =============================================================================
# 13. PAYCHANGU (subscription payments)
# =============================================================================
# Test/live determined by which keys you paste from
# dashboard.paychangu.com → Settings → API & Webhooks.
# The webhook secret is separate and only used to verify signatures.
PAYCHANGU_SECRET_KEY = os.getenv('PAYCHANGU_SECRET_KEY')
PAYCHANGU_WEBHOOK_SECRET = os.getenv('PAYCHANGU_WEBHOOK_SECRET')


# =============================================================================
# 14. WHATSAPP BUSINESS API (Cloud API / Meta Graph)
# =============================================================================
# Used for sending verification links, receipts, statements, invite
# links, and (via webhook) receiving inbound messages.
#
# Where to get these values:
#   - Meta Business Suite → Apps → your app → WhatsApp → Basic setup
#     → WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN
#     → App settings → Basic → App Secret → WHATSAPP_APP_SECRET
#   - You choose WHATSAPP_VERIFY_TOKEN yourself; enter the same value in
#     the Meta webhook configuration so Meta can verify your endpoint.
#
# Webhook URL to register with Meta:
#   https://yourdomain.com/payments/webhooks/whatsapp/
#   (handled by payments.views.WhatsAppWebhookView)
#
# Notes:
#   - WHATSAPP_ACCESS_TOKEN in production should be a System User token,
#     not a temporary one from Basic setup. Temporary tokens expire in
#     ~24h; System User tokens can be set to never expire. See:
#     Business Settings → Users → System Users → Generate Token.
#   - Never expose APP_SECRET or ACCESS_TOKEN in templates or client-side JS.

# --- Credentials -----------------------------------------------------------
WHATSAPP_PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
WHATSAPP_ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
WHATSAPP_VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN')
WHATSAPP_APP_SECRET = os.getenv('WHATSAPP_APP_SECRET')

# --- Graph API version -----------------------------------------------------
# Meta deprecates Graph API versions on a rolling ~2-year cycle. Keep
# this current: a stale version hard-rejects with an OAuthException.
# Read by accounts/verification.py, which builds every outbound URL.
#
# Current version list: https://developers.facebook.com/docs/graph-api/changelog
WHATSAPP_API_VERSION = os.getenv('WHATSAPP_API_VERSION', 'v23.0')

# --- Verification template (optional but recommended) ----------------------
# Meta only accepts free-form text within a 24-hour "re-engagement
# window" that opens when the recipient messages the business first.
# A brand-new signup has never messaged us — so a plain-text verification
# send will fail with error 131047 unless a template is used.
#
# Register a UTILITY template in Meta Business Suite → WhatsApp Manager
# → Message Templates with a body like:
#
#   "Confirm your ChumaFlow account by opening this link:
#    {{1}}
#
#    This link expires in 3 days. If you didn't sign up, ignore this message."
#
# Once approved, set WHATSAPP_VERIFICATION_TEMPLATE_NAME in .env to the
# template name you chose. See accounts/verification.py for the full
# two-attempt strategy (template first, free-form text as fallback).
#
# Leave blank to disable the template attempt (text-only sends will
# still work inside the 24h window and on test numbers).
WHATSAPP_VERIFICATION_TEMPLATE_NAME = os.getenv(
    'WHATSAPP_VERIFICATION_TEMPLATE_NAME', ''
)
WHATSAPP_VERIFICATION_TEMPLATE_LANG = os.getenv(
    'WHATSAPP_VERIFICATION_TEMPLATE_LANG', 'en_US'
)


# =============================================================================
# 15. DEFAULT PRIMARY KEY FIELD
# =============================================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# =============================================================================
# 16. SECURITY HEADERS (Production only)
# =============================================================================

if not DEBUG:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000          # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', default=True)

    # Required when running behind a reverse proxy that terminates HTTPS
    # (Nginx, Apache, Cloudflare, cPanel, etc.)
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# =============================================================================
# 17. LOGGING (so production errors appear in journalctl)
# =============================================================================

# Without this, unhandled exceptions under Gunicorn can vanish silently —
# you get a 500 on the page with nothing in the log. This ensures the
# traceback is written to stderr, which systemd captures into journalctl.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        # Silence the noisy startup line from django.db.backends on every query
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}