from django.contrib import admin

from .models import Column, Project, ProjectEntry, ProjectMilestone, ProjectUpdate, Task, TaskComment


class ColumnInline(admin.TabularInline):
    model = Column
    extra = 0
    fields = ("title", "order", "hidden", "is_archived")


class TaskCommentInline(admin.TabularInline):
    model = TaskComment
    extra = 0
    fields = ("author", "comment", "created_on")
    readonly_fields = ("created_on",)
    raw_id_fields = ("author",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "team", "lead", "status", "priority", "start_date", "end_date", "created_at")
    list_filter = ("status", "priority")
    search_fields = ("title", "workspace__workspace_name", "team__title", "lead__email")
    raw_id_fields = ("workspace", "team", "created_by", "lead")
    date_hierarchy = "created_at"
    inlines = [ColumnInline]
    list_per_page = 25


@admin.register(Column)
class ColumnAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "order", "hidden", "is_archived")
    list_filter = ("hidden", "is_archived")
    search_fields = ("title", "project__title")
    raw_id_fields = ("project", "workspace", "team", "created_by")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "team", "column", "status", "priority", "due_date", "created_at")
    list_filter = ("status", "priority")
    search_fields = ("title", "workspace__workspace_name", "team__title")
    raw_id_fields = ("workspace", "team", "project", "column", "created_by")
    date_hierarchy = "created_at"
    inlines = [TaskCommentInline]
    list_per_page = 50


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ("task", "author", "created_on")
    search_fields = ("task__title", "author__email", "comment")
    raw_id_fields = ("task", "author")


@admin.register(ProjectEntry)
class ProjectEntryAdmin(admin.ModelAdmin):
    list_display = ("project", "task", "minutes", "is_tracked", "created_by", "created_at")
    list_filter = ("is_tracked",)
    search_fields = ("project__title", "created_by__email")
    raw_id_fields = ("workspace", "team", "project", "task", "created_by")
    date_hierarchy = "created_at"


@admin.register(ProjectMilestone)
class ProjectMilestoneAdmin(admin.ModelAdmin):
    list_display = ("name", "target_date", "creator", "created_at")
    search_fields = ("name",)
    raw_id_fields = ("creator",)


@admin.register(ProjectUpdate)
class ProjectUpdateAdmin(admin.ModelAdmin):
    list_display = ("Project", "author", "privacy", "created_on")
    list_filter = ("privacy",)
    search_fields = ("Project__title", "author__email")
    raw_id_fields = ("workspace", "Project", "author")
