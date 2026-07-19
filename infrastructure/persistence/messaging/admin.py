from django.contrib import admin

from infrastructure.persistence.messaging.models import (
    Conversation,
    ConversationParticipant,
    Message,
)


class ParticipantInline(admin.TabularInline):
    model = ConversationParticipant
    extra = 0
    readonly_fields = ("joined_at",)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation_type", "workspace", "created_at")
    list_filter = ("conversation_type",)
    search_fields = ("id",)
    inlines = [ParticipantInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "message_type", "is_deleted", "created_at")
    list_filter = ("message_type", "is_deleted")
    search_fields = ("body",)
    readonly_fields = ("created_at", "updated_at")
