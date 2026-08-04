from django.contrib import admin

from infrastructure.persistence.tagging.models import Tag


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "workspace", "kind", "is_deleted")
    list_filter = ("kind", "is_deleted")
    search_fields = ("name", "slug", "namespace")
    ordering = ("workspace", "slug")
