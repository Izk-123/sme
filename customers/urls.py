"""
URL routes for the customers app.

Mounted at /customers/ by config/urls.py — so every path below is
relative to that prefix.

Order matters for patterns at the same depth
--------------------------------------------
Django matches patterns in list order and does not backtrack. So a bare
variable segment like <int:pk>/ must come after any literal sibling
("add/", "payment/add/") that sits at the same position. If "add/" came
after <int:pk>/, Django would try <int:pk>/ on the URL "/customers/add/",
fail to convert "add" to an int, and — because it does not backtrack to
later patterns — return 404.

Deeper literal suffixes like <int:pk>/toggle-active/ are safe either way:
<int:pk>/ simply won't match a longer URL (there's nothing to consume
the trailing segment), so Django moves on to the next pattern. Keeping
them below the detail route is a readability convention, not a
correctness requirement.
"""
from django.urls import path

from . import views

# No app_name / namespace: existing templates across the project use
# {% url 'customer_list' %} and {% url 'payment_add' %} without a prefix.
# Adding app_name here would break every one of those.

urlpatterns = [
    # ---- List --------------------------------------------------------
    # GET /customers/
    path(
        "",
        views.CustomerListView.as_view(),
        name="customer_list",
    ),

    # ---- Create ------------------------------------------------------
    # GET/POST /customers/add/
    # Literal segment at this depth — must come before <int:pk>/ below,
    # because Django stops at the first pattern that could match the
    # path's first segment.
    path(
        "add/",
        views.CustomerCreateView.as_view(),
        name="customer_add",
    ),

    # ---- Record a payment -------------------------------------------
    # GET/POST /customers/payment/add/
    # Also literal, also before <int:pk>/.
    path(
        "payment/add/",
        views.PaymentCreateView.as_view(),
        name="payment_add",
    ),

    # ---- Detail ------------------------------------------------------
    # GET /customers/<pk>/
    path(
        "<int:pk>/",
        views.CustomerDetailView.as_view(),
        name="customer_detail",
    ),

    # ---- Activate / deactivate ---------------------------------------
    # POST /customers/<pk>/toggle-active/
    # A deeper literal suffix on the same prefix. Order against the bare
    # detail route is irrelevant (see module docstring) — grouped here
    # with the other detail-page actions for readability.
    path(
        "<int:pk>/toggle-active/",
        views.CustomerToggleActiveView.as_view(),
        name="customer_toggle_active",
    ),
]