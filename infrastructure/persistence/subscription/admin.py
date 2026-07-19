from django.contrib import admin

from .models import Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("title", "price", "limits", "is_default")
    list_filter = ("is_default",)
    search_fields = ("title",)
