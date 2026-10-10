from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    list_display = ("recipient", "title", "level", "is_read", "created_at")
    list_filter = ("level", "is_read")
    search_fields = ("recipient__username", "title")
