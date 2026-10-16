"""
Root URL configuration for the SME Business OS project.

This module routes incoming HTTP requests to the appropriate app.
Media files are served during development.

Two URL namespaces share the /accounts/ prefix and that's deliberate:
  * /accounts/google/…   →  django-allauth (the OAuth dance)
  * /accounts/signup/…   →  our own signup flow, via accounts.urls
Allauth only claims what it needs under its own subpath; the rest of
/accounts/ belongs to us.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # ===== Django Admin =====
    path('admin/', admin.site.urls),

    # ===== django-allauth =====
    # Provides:
    #   /accounts/google/login/          → starts the OAuth dance
    #   /accounts/google/login/callback/ → Google redirects here
    #   /accounts/3rdparty/…             → provider error pages
    #   /accounts/social/signup/         → only reached if AUTO_SIGNUP
    #                                       is False; we have it True
    # Everything under /accounts/ that allauth doesn't define falls
    # through to our own accounts app below.
    path('accounts/', include('allauth.urls')),

    # ===== Custom Apps =====
    # Accounts (Authentication, Profile, Team, Settings)
    path('', include('accounts.urls')),

    # Core (Dashboard, Onboarding, Action Menus)
    path('', include('core.urls')),

    # Sales & Inventory
    path('sales/', include('sales.urls')),

    # Expenses
    path('expenses/', include('expenses.urls')),

    # Reports (Business Intelligence)
    path('reports/', include('reports.urls')),

    # Suppliers
    path('suppliers/', include('suppliers.urls')),

    # Customers
    path('customers/', include('customers.urls')),

    path('subscriptions/', include('subscriptions.urls')),
    path('payments/', include('payments.urls')),
]

# ===== Media Files (Development only) =====
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)