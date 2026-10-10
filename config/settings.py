"""
Django settings for ChumaFlow (SME Business OS).

Single settings file that works for both development and production.
Environment-specific behaviour is controlled via .env variables.

Minimum .env for PRODUCTION:
    DEBUG=False
    SECRET_KEY=<strong-random-key>
    ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
    DB_ENGINE=postgresql
    DB_NAME=...  DB_USER=...  DB_PASSWORD=...  DB_HOST=...  DB_PORT=...

Optional:
    USE_REDIS=True/False, REDIS_HOST, REDIS_PORT
    CSRF_TRUSTED_ORIGINS=https://yourdomain.com
    EMAIL_* , PAYCHANGU_* , BASE_URL, SECURE_SSL_REDIRECT
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
# 4. AUTHENTICATION & USER MODEL
# =============================================================================

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"


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

    # Custom middleware — order matters
    'core.middleware.CurrentMembershipMiddleware',
    'subscriptions.middleware.SubscriptionMiddleware',
    'core.middleware.ForcePasswordChangeMiddleware',

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

# DB_ENGINE=postgresql → Postgres; anything else (default) → SQLite.
if os.getenv('DB_ENGINE', 'sqlite').lower() == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME'),
            'USER': os.getenv('DB_USER'),
            'PASSWORD': os.getenv('DB_PASSWORD'),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
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

# Whitenoise's manifest storage requires collectstatic — only enable in prod.
# In dev it raises "Missing staticfiles manifest entry" errors.
if not DEBUG:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }


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

# Absolute base URL used in emails (password reset, invites, etc.)
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
# 14. DEFAULT PRIMARY KEY FIELD
# =============================================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# =============================================================================
# 15. SECURITY HEADERS (Production only)
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