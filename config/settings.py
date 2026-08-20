"""
Django settings for SME Business OS project.

This file is organized into clear sections for maintainability.
Environment variables are loaded from a .env file for security.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# =============================================================================
# 1. PATH SETUP & ENVIRONMENT VARIABLES
# =============================================================================

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file (keeps secrets out of code)
load_dotenv(BASE_DIR / '.env')


# =============================================================================
# 2. SECURITY & DEBUG SETTINGS
# =============================================================================

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-your-fallback-key-here')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True') == 'True'

# Comma-separated list of allowed hosts (e.g., localhost, yourdomain.com)
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')


# =============================================================================
# 3. APPLICATION DEFINITION
# =============================================================================

INSTALLED_APPS = [
    # Django Admin / Unfold (must come first)
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',

    # Django Core Apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party & Async
    'channels',

    # Custom Apps
    'accounts',
    'organizations',
    'customers',
    'sales',
    'expenses',
    'reports',
    'suppliers',
    'core',
]

# Custom admin theme configuration (Unfold)
UNFOLD = {
    "SITE_TITLE": "SME Business OS",
    "SITE_HEADER": "SME Business OS",
    "SITE_SYMBOL": "storefront",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
}


# =============================================================================
# 4. AUTHENTICATION & USER MODEL
# =============================================================================

# Custom User model (accounts.User) instead of Django's default
AUTH_USER_MODEL = "accounts.User"

# Login / Logout URLs
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"


# =============================================================================
# 5. MIDDLEWARE LAYER
# =============================================================================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',

    # Custom Middleware (Order is important)
    # Must run after AuthenticationMiddleware, before anything reading request.org
    'core.middleware.CurrentMembershipMiddleware',
    'core.middleware.ForcePasswordChangeMiddleware',

    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# =============================================================================
# 6. ASGI / CHANNELS (Real-time / Notifications)
# =============================================================================

# Points to config/asgi.py for ASGI server (Daphne / Uvicorn)
ASGI_APPLICATION = 'config.asgi.application'

# Channel Layers for WebSocket communication
# For production, use Redis. For local dev without Redis, use InMemory.
if os.getenv('USE_REDIS', 'True') == 'True':
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [("127.0.0.1", 6379)],
            },
        },
    }
else:
    # Fallback for development when Redis is not installed
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer"
        },
    }


# =============================================================================
# 7. URLS, TEMPLATES, WSGI
# =============================================================================

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],   # Global template folder
        'APP_DIRS': True,                   # Look inside each app's templates/
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Custom context processor for low-stock alerts
                'core.context_processors.low_stock_processor',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# =============================================================================
# 8. DATABASE
# =============================================================================

# Currently using SQLite for development.
# For production (cPanel), uncomment the PostgreSQL settings and install psycopg2.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Example PostgreSQL configuration for production (uncomment when ready):
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': os.getenv('DB_NAME'),
#         'USER': os.getenv('DB_USER'),
#         'PASSWORD': os.getenv('DB_PASSWORD'),
#         'HOST': os.getenv('DB_HOST'),
#         'PORT': os.getenv('DB_PORT', '5432'),
#     }
# }


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
TIME_ZONE = 'Africa/Blantyre'           # Change to 'Africa/Blantyre' if you prefer local time
USE_I18N = True
USE_TZ = True


# =============================================================================
# 11. STATIC & MEDIA FILES
# =============================================================================

# --- Static Files (CSS, JS, Images) ---
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
# STATIC_ROOT = BASE_DIR / 'staticfiles'   # Uncomment for production (collectstatic)

# --- Media Files (User Uploads: Profile Photos, Product Images, Receipts) ---
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Note: In production (cPanel/Nginx/Apache), you must configure your web server
# to serve files from MEDIA_ROOT at the MEDIA_URL path.


# =============================================================================
# 12. EMAIL CONFIGURATION (cPanel SMTP)
# =============================================================================

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'mail.yourdomain.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 465))
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'True') == 'True'
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'False') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)

# Base URL for generating absolute links in emails (e.g., password resets, invites)
BASE_URL = os.getenv('BASE_URL', 'http://localhost:8000')


# =============================================================================
# 13. DEFAULT PRIMARY KEY FIELD
# =============================================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'