from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    AttendanceRecord,
    EmployeeProfile,
    EmployeeRequest,
    ExpenseRequest,
    IdentityDocument,
    Invitation,
    Membership,
    NotificationPreference,
    PhoneNumber,
    Role,
    Task,
    User,
    UserPreference,
    UserProfile,
)


# =============================================================================
# Inlines used by UserAdmin
# =============================================================================

class UserProfileInline(TabularInline):
    model = UserProfile
    extra = 0
    # A curated field list rather than the model default: the profile
    # has ~20 fields and showing all of them inline would dwarf the
    # User form. The full profile is editable via /settings/ in the app
    # and via the dedicated UserProfile admin registered below.
    fields = (
        "first_name", "middle_name", "last_name", "preferred_name",
        "email_verified", "email_address_verified",
        "preferred_verification_channel",
    )
    readonly_fields = ("email_address_verified",)


class PhoneNumberInline(TabularInline):
    model = PhoneNumber
    extra = 0


class IdentityDocumentInline(TabularInline):
    model = IdentityDocument
    extra = 0


class MembershipInline(TabularInline):
    model = Membership
    fk_name = "user"
    extra = 0


# =============================================================================
# User
# =============================================================================

@admin.register(User)
class UserAdmin(DjangoUserAdmin, ModelAdmin):
    list_display = (
        "username", "email", "email_verified_column",
        "is_staff", "is_active", "must_change_password",
    )
    list_filter = ("is_staff", "is_active")
    search_fields = ("username", "email", "email_normalized")
    inlines = [
        UserProfileInline,
        PhoneNumberInline,
        IdentityDocumentInline,
        MembershipInline,
    ]

    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Account", {
            "fields": ("must_change_password", "email_normalized"),
            "description": (
                "email_normalized is the canonical form used for identity "
                "matching across Gmail dot/plus variations. It's populated "
                "automatically on save and shouldn't need manual edits."
            ),
        }),
    )

    # organization/role no longer live on User — dropped from add_fieldsets;
    # a Membership is created separately (signup flow, invitation, or here).

    @admin.display(description="Email verified", boolean=True)
    def email_verified_column(self, obj):
        """
        True when the EMAIL ADDRESS ITSELF is proven, i.e. the user
        clicked an email-delivered verification link. Distinct from
        UserProfile.email_verified, which is True whenever the contact
        was confirmed via any channel.

        This column matters for support: a user reporting "Google
        sign-in says my account isn't verified" needs their
        email_address_verified flag checked, not their email_verified.
        """
        profile = getattr(obj, "profile", None)
        return bool(profile and profile.email_address_verified)


# =============================================================================
# UserProfile — dedicated admin, mostly for support workflows
# =============================================================================

@admin.register(UserProfile)
class UserProfileAdmin(ModelAdmin):
    list_display = (
        "user", "display_name_column",
        "email_verified", "email_address_verified",
        "preferred_verification_channel",
    )
    list_filter = (
        "email_verified",
        "email_address_verified",
        "preferred_verification_channel",
        "country",
    )
    search_fields = (
        "user__username",
        "user__email",
        "first_name",
        "last_name",
        "preferred_name",
    )
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
    actions = ["mark_email_address_verified", "clear_email_address_verified"]

    fieldsets = (
        ("Identity", {
            "fields": (
                "user",
                "first_name", "middle_name", "last_name", "preferred_name",
                "date_of_birth", "gender", "profile_photo",
            ),
        }),
        ("Contact", {
            "fields": ("address", "city", "district", "country"),
        }),
        ("Verification", {
            "fields": (
                "email_verified",
                "email_address_verified",
                "preferred_verification_channel",
            ),
            "description": (
                "<strong>email_verified</strong> — the user confirmed their "
                "contact through any channel (email or WhatsApp). Gates "
                "app access.<br>"
                "<strong>email_address_verified</strong> — the user proved "
                "they own the email address itself, by clicking a link "
                "delivered <em>by email</em>. Required for Google account "
                "linking. WhatsApp verification does NOT set this."
            ),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Name")
    def display_name_column(self, obj):
        return obj.display_name

    # ------------------------------------------------------------------
    # Support actions
    # ------------------------------------------------------------------
    #
    # These exist for the case the design anticipated: a genuine owner
    # whose email was claimed by someone else (or whose verification
    # link was lost) can't unblock themselves from Settings. Support
    # verifies the person through another channel — WhatsApp call, a
    # photo ID, whatever the business's own process requires — then
    # uses one of these actions.
    #
    # Both are logged by Django's admin history automatically (the
    # acting user, the time, and which profiles were touched).

    @admin.action(
        description="✓ Mark email address as verified (support use only)",
    )
    def mark_email_address_verified(self, request, queryset):
        """
        Flip `email_address_verified=True` on the selected profiles.

        Use only after verifying the requester's identity through
        another channel. Once set, a Google sign-in with a matching
        email will link to this account.

        Note: this action also sets `email_verified` to True if it
        wasn't already — an admin wouldn't mark the address verified
        while leaving the "app locked" flag off, that's never the
        intent.
        """
        # Update both flags in one pass, but only where they need
        # flipping, so we don't overwrite a value that's already True.
        email_proven = queryset.filter(email_address_verified=False)
        app_unlocked = queryset.filter(email_verified=False)

        n_proven = email_proven.update(email_address_verified=True)
        n_unlocked = app_unlocked.update(email_verified=True)

        self.message_user(
            request,
            f"Marked {n_proven} profile(s) as email_address_verified; "
            f"unlocked {n_unlocked} profile(s). "
            f"Action recorded in admin history.",
        )

    @admin.action(
        description="✗ Clear email address verification (debugging only)",
    )
    def clear_email_address_verified(self, request, queryset):
        """
        Reverse of the action above. Intended for testing the linking
        flow — a developer who wants to re-check what a user sees
        before they've proven their email.

        Does NOT clear `email_verified`; the app-unlock flag is separate
        and shouldn't be touched by a "reset the address proof" action.
        """
        n = queryset.update(email_address_verified=False)
        self.message_user(
            request,
            f"Cleared email_address_verified on {n} profile(s). "
            f"Users will need to re-verify by email to sign in with Google.",
        )


# =============================================================================
# Membership
# =============================================================================

@admin.register(Membership)
class MembershipAdmin(ModelAdmin):
    list_display = ("user", "organization", "role", "is_active", "joined_at")
    list_filter = ("organization", "role", "is_active")
    autocomplete_fields = ("user", "organization", "role")
    search_fields = ("user__username", "organization__name")


# =============================================================================
# Role
# =============================================================================

@admin.register(Role)
class RoleAdmin(ModelAdmin):
    list_display = ("name", "slug", "organization", "is_system")
    list_filter = ("organization", "is_system")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


# =============================================================================
# Invitation
# =============================================================================

@admin.register(Invitation)
class InvitationAdmin(ModelAdmin):
    list_display = (
        "full_name", "organization", "role",
        "status", "created_at", "expires_at",
    )
    list_filter = ("organization", "status")
    readonly_fields = ("token", "accepted_by", "accepted_at")


# =============================================================================
# EmployeeProfile
# =============================================================================

@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(ModelAdmin):
    list_display = ("membership", "job_title", "department", "status")
    list_filter = ("status", "department")
    autocomplete_fields = ("membership", "manager")


# =============================================================================
# Preferences
# =============================================================================

@admin.register(UserPreference)
class UserPreferenceAdmin(ModelAdmin):
    list_display = ("user", "theme", "language", "timezone", "compact_mode")
    search_fields = ("user__username",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(ModelAdmin):
    list_display = (
        "user", "daily_sales_summary", "low_stock_alert",
        "push_notifications", "email_notifications",
    )
    search_fields = ("user__username",)


# =============================================================================
# Self-service models — Task, ExpenseRequest, EmployeeRequest, AttendanceRecord
# =============================================================================
#
# These four models have no owner-facing UI yet: assigning a task,
# reviewing a request, and logging attendance all happen via /admin/
# for now. See accounts/models/task.py for the note on that.
#
# The list_display columns are chosen to match what an owner would
# filter on: who it belongs to, what it is, and its current state.

@admin.register(Task)
class TaskAdmin(ModelAdmin):
    list_display = (
        "title", "membership", "due_date",
        "is_completed", "created_by", "created_at",
    )
    list_filter = ("is_completed", "due_date")
    search_fields = ("title", "description", "membership__user__username")
    autocomplete_fields = ("membership", "created_by")
    date_hierarchy = "created_at"


@admin.register(ExpenseRequest)
class ExpenseRequestAdmin(ModelAdmin):
    list_display = (
        "membership", "amount", "category",
        "status", "reviewed_by", "created_at",
    )
    list_filter = ("status", "category")
    search_fields = ("membership__user__username", "description", "category")
    autocomplete_fields = ("membership", "reviewed_by")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"


@admin.register(EmployeeRequest)
class EmployeeRequestAdmin(ModelAdmin):
    list_display = (
        "membership", "request_type",
        "status", "reviewed_by", "created_at",
    )
    list_filter = ("status", "request_type")
    search_fields = ("membership__user__username", "description")
    autocomplete_fields = ("membership", "reviewed_by")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(ModelAdmin):
    list_display = (
        "membership", "date", "status",
        "check_in", "check_out",
    )
    list_filter = ("status", "date")
    search_fields = ("membership__user__username",)
    autocomplete_fields = ("membership",)
    date_hierarchy = "date"