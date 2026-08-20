"""
Root URL configuration for the SME Business OS project.

This module routes incoming HTTP requests to the appropriate app.
Media files are served during development.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # ===== Django Admin =====
    path('admin/', admin.site.urls),

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
]

# ===== Media Files (Development only) =====
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)