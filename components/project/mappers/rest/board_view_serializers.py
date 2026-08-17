"""Serializers for the boards-as-views read API (ADR 0030 P2a).

Read-only projections. The lane serializer mirrors ``ColumnSerializer``'s
windowed-lane contract (``tasks`` / ``tasks_total`` / ``tasks_has_more``,
tasks rendered by the same ``TaskSerializer``) so the HUD's flag flip is a
lane-source swap, not a re-plumb; it also exposes ``title`` as an alias of
``name`` because ``HudKanbanBoard`` renders ``lane.title`` today.
"""

from __future__ import annotations

from rest_framework import serializers

from components.project.mappers.rest.project_serializers import TaskSerializer
from infrastructure.persistence.project.models import BoardView, WorkflowStatus


class BoardViewSerializer(serializers.ModelSerializer):
    """One saved view — a row in the views bar."""

    class Meta:
        model = BoardView
        fields = [
            "id",
            "team",
            "workspace",
            "name",
            "slug",
            "filter",
            "group_by",
            "order",
            "is_system",
        ]
        read_only_fields = fields


class WorkflowStatusLaneSerializer(serializers.ModelSerializer):
    """One status lane of a view board, with its windowed matching tasks.

    Lanes only reach this serializer through ``OrmBoardViewQueryRepository``,
    which attaches ``windowed_tasks`` + ``tasks_total`` (a lane is NEVER
    serialized whole — performance.md §11; the remainder pages through
    GET /project/views/<view_id>/lanes/<status_id>/tasks/). There is
    deliberately no query-the-lane fallback here: a missing window is an
    empty lane, not an unbounded one.
    """

    title = serializers.CharField(source="name", read_only=True)
    tasks = serializers.SerializerMethodField()
    tasks_total = serializers.SerializerMethodField()
    tasks_has_more = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowStatus
        fields = [
            "id",
            "name",
            "title",
            "category",
            "order",
            "tasks",
            "tasks_total",
            "tasks_has_more",
        ]
        read_only_fields = fields

    def get_tasks(self, obj) -> list:
        windowed = getattr(obj, "windowed_tasks", None) or []
        return TaskSerializer(windowed, many=True, context=self.context).data

    def get_tasks_total(self, obj) -> int:
        return getattr(obj, "tasks_total", 0) or 0

    def get_tasks_has_more(self, obj) -> bool:
        windowed = getattr(obj, "windowed_tasks", None) or []
        return self.get_tasks_total(obj) > len(windowed)
