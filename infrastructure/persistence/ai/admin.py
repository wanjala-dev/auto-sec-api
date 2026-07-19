from django.contrib import admin

from infrastructure.persistence.ai.agents.models import (
    Agent,
    AgentComment,
    AgentExecution,
    AgentFollow,
    AgentProfile,
    AgentRating,
    AgentReaction,
    AgentShare,
    AgentType,
    DeepArtifact,
    DeepRun,
    DeepRunLog,
    WorkspaceAgentType,
)
from infrastructure.persistence.ai.models import (
    AIPermissionGrant,
    AITeammateProfile,
    Document,
    DocumentChunk,
)


# ── Agent Types ───────────────────────────────────────────────────────


@admin.register(AgentType)
class AgentTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")


@admin.register(WorkspaceAgentType)
class WorkspaceAgentTypeAdmin(admin.ModelAdmin):
    list_display = ("workspace", "agent_type", "is_enabled", "created_at")
    list_filter = ("is_enabled",)
    search_fields = ("workspace__workspace_name", "agent_type__slug")
    raw_id_fields = ("workspace", "agent_type")


# ── Agents ────────────────────────────────────────────────────────────


class AgentExecutionInline(admin.TabularInline):
    model = AgentExecution
    extra = 0
    fields = ("id", "status", "success", "execution_time_ms", "created_at")
    readonly_fields = ("id", "status", "success", "execution_time_ms", "created_at")
    show_change_link = True
    max_num = 10
    ordering = ("-created_at",)


class AgentProfileInline(admin.StackedInline):
    model = AgentProfile
    extra = 0
    can_delete = False


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("agent_id", "agent_type", "user", "workspace_id", "status", "created_at")
    list_filter = ("agent_type", "status")
    search_fields = ("agent_id", "agent_type", "user__email", "workspace_id")
    raw_id_fields = ("user",)
    readonly_fields = ("agent_id", "created_at", "updated_at")
    date_hierarchy = "created_at"
    inlines = [AgentProfileInline, AgentExecutionInline]
    list_per_page = 25


@admin.register(AgentExecution)
class AgentExecutionAdmin(admin.ModelAdmin):
    list_display = ("id", "agent", "status", "success", "execution_time_ms", "progress", "created_at")
    list_filter = ("status", "success")
    search_fields = ("agent__agent_id", "query", "task_id")
    raw_id_fields = ("agent", "triggered_by")
    readonly_fields = ("id", "created_at", "updated_at")
    date_hierarchy = "created_at"
    list_per_page = 50


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display = ("agent", "display_name", "visibility", "created_at")
    list_filter = ("visibility",)
    search_fields = ("display_name", "agent__agent_id")
    raw_id_fields = ("agent",)


admin.site.register(AgentFollow)
admin.site.register(AgentReaction)
admin.site.register(AgentRating)
admin.site.register(AgentComment)
admin.site.register(AgentShare)


# ── Deep Runs ─────────────────────────────────────────────────────────


class DeepRunLogInline(admin.TabularInline):
    model = DeepRunLog
    extra = 0
    fields = ("event_type", "status", "agent_type", "tool_name", "created_at")
    readonly_fields = fields
    max_num = 20
    ordering = ("-created_at",)


class DeepArtifactInline(admin.TabularInline):
    model = DeepArtifact
    extra = 0
    fields = ("task_id", "uri", "summary", "created_at")
    readonly_fields = ("created_at",)


@admin.register(DeepRun)
class DeepRunAdmin(admin.ModelAdmin):
    list_display = ("thread_id", "plan_id", "user", "workspace", "status", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("thread_id", "plan_id", "user__email", "workspace__workspace_name")
    raw_id_fields = ("user", "workspace")
    readonly_fields = ("thread_id", "created_at", "updated_at")
    date_hierarchy = "created_at"
    inlines = [DeepRunLogInline, DeepArtifactInline]


@admin.register(DeepRunLog)
class DeepRunLogAdmin(admin.ModelAdmin):
    list_display = ("deep_run", "event_type", "status", "agent_type", "tool_name", "created_at")
    list_filter = ("event_type", "status")
    search_fields = ("deep_run__thread_id", "event_type", "agent_type")
    raw_id_fields = ("deep_run",)


@admin.register(DeepArtifact)
class DeepArtifactAdmin(admin.ModelAdmin):
    list_display = ("deep_run", "task_id", "uri", "created_at")
    search_fields = ("deep_run__thread_id", "task_id", "uri")
    raw_id_fields = ("deep_run",)


# ── AI Teammate ───────────────────────────────────────────────────────


@admin.register(AITeammateProfile)
class AITeammateProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "workspace", "user", "status", "is_enabled", "last_run_at")
    list_filter = ("status", "is_enabled")
    search_fields = ("display_name", "workspace__workspace_name", "user__email")
    raw_id_fields = ("workspace", "user")


@admin.register(AIPermissionGrant)
class AIPermissionGrantAdmin(admin.ModelAdmin):
    list_display = ("workspace", "principal", "role", "scope_type", "status", "created_at")
    list_filter = ("role", "status", "scope_type")
    search_fields = ("workspace__workspace_name",)
    raw_id_fields = ("workspace", "principal")


# ── Documents ─────────────────────────────────────────────────────────


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "created_at")
    search_fields = ("title", "source")


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "chunk_index", "created_at")
    search_fields = ("document__title",)
    raw_id_fields = ("document",)
