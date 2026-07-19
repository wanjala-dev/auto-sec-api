from django.contrib import admin

from .models import HoneypotAttempt


@admin.register(HoneypotAttempt)
class HoneypotAttemptAdmin(admin.ModelAdmin):
    list_display = ("attempted_at", "username", "ip_address", "path", "method")
    readonly_fields = (
        "attempted_at",
        "username",
        "password",
        "ip_address",
        "user_agent",
        "path",
        "method",
        "referer",
    )
    search_fields = ("username", "ip_address", "user_agent", "path")
    list_filter = ("method", "attempted_at")
    ordering = ("-attempted_at",)
