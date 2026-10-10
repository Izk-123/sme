from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    EmployeeProfile,
    IdentityDocument,
    Invitation,
    Membership,
    NotificationPreference,
    PhoneNumber,
    Role,
    User,
    UserPreference,
    UserProfile,
)


class UserProfileInline(TabularInline):
    model = UserProfile
    extra = 0


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


@admin.register(User)
class UserAdmin(DjangoUserAdmin, ModelAdmin):
    list_display = ("username", "email", "is_staff", "is_active", "must_change_password")
    list_filter = ("is_staff", "is_active")
    inlines = [UserProfileInline, PhoneNumberInline, IdentityDocumentInline, MembershipInline]
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Account", {"fields": ("must_change_password",)}),
    )
    # organization/role no longer live on User - dropped from add_fieldsets;
    # a Membership is created separately (signup flow, invitation, or here in admin).


@admin.register(Membership)
class MembershipAdmin(ModelAdmin):
    list_display = ("user", "organization", "role", "is_active", "joined_at")
    list_filter = ("organization", "role", "is_active")
    autocomplete_fields = ("user", "organization", "role")
    search_fields = ("user__username", "organization__name")


@admin.register(Role)
class RoleAdmin(ModelAdmin):
    list_display = ("name", "slug", "organization", "is_system")
    list_filter = ("organization", "is_system")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Invitation)
class InvitationAdmin(ModelAdmin):
    list_display = ("full_name", "organization", "role", "status", "created_at", "expires_at")
    list_filter = ("organization", "status")
    readonly_fields = ("token", "accepted_by", "accepted_at")


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(ModelAdmin):
    list_display = ("membership", "job_title", "department", "status")
    list_filter = ("status", "department")
    autocomplete_fields = ("membership", "manager")


@admin.register(UserPreference)
class UserPreferenceAdmin(ModelAdmin):
    list_display = ("user", "theme", "language", "timezone", "compact_mode")
    search_fields = ("user__username",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(ModelAdmin):
    list_display = ("user", "daily_sales_summary", "low_stock_alert", "push_notifications", "email_notifications")
    search_fields = ("user__username",)
