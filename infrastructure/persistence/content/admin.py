from django.contrib import admin

from infrastructure.persistence.content.models import (
    Newsletter,
    Subscriber,
    WritingDraft,
    WritingTemplate,
)


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "workspace", "subscribed_at")
    search_fields = ("email", "name")
    list_filter = ("workspace",)


@admin.register(Newsletter)
class NewsletterAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "status", "sent_at", "created_at")
    list_filter = ("status", "workspace")
    search_fields = ("title",)
    readonly_fields = ("created_at", "updated_at", "sent_at", "pdf_generated_at")


@admin.register(WritingTemplate)
class WritingTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "workspace", "is_seeded", "created_at")
    list_filter = ("kind", "is_seeded", "workspace")
    search_fields = ("name", "description")


@admin.register(WritingDraft)
class WritingDraftAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "kind", "status", "author", "updated_at")
    list_filter = ("kind", "status", "workspace")
    search_fields = ("title",)
    readonly_fields = ("created_at", "updated_at", "pdf_generated_at")
