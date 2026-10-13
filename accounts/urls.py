from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("signup/", views.SignupView.as_view(), name="signup"),
    path("login/", views.BusinessLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("change-password/", views.ChangePasswordView.as_view(), name="change_password"),
    path("profile/", views.ProfileRedirectView.as_view(), name="profile"),
    path("settings/", views.SettingsView.as_view(), name="settings"),

    # Team management (owner-only)
    path("team/", views.TeamListView.as_view(), name="team_list"),
    path("team/invite/", views.InviteEmployeeView.as_view(), name="invite_employee"),
    path("team/invite/success/", views.InviteSuccessView.as_view(), name="invite_success"),
    path("team/<int:pk>/toggle-active/", views.ToggleEmployeeActiveView.as_view(), name="toggle_employee_active"),

    # Invitation acceptance (public)
    path("invite/<str:token>/", views.AcceptInvitationView.as_view(), name="accept_invitation"),

    # Verification. These two literal paths MUST be registered before
    # verify-email/<str:token>/ below — the str converter is greedy
    # enough to match "required" and "resend" as token values otherwise,
    # which would route both to VerifyEmailView and show "link isn't
    # valid" instead of the intended page.
    path(
        "verify-email/required/",
        views.VerifyEmailRequiredView.as_view(),
        name="verify_email_required",
    ),
    path(
        "verify-email/resend/",
        views.ResendVerificationEmailView.as_view(),
        name="resend_verification_email",
    ),
    path(
        "verify-email/<str:token>/",
        views.VerifyEmailView.as_view(),
        name="verify_email",
    ),
]